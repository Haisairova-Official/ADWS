using System.Diagnostics;
using System.Drawing.Drawing2D;

namespace Adws.Windows;

internal sealed class DesktopSurface : IDisposable
{
    private readonly HostConfig config;
    private readonly Dictionary<string,Button> buttons = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<uint,string> paths = [];
    private readonly List<string> pins = [];
    private readonly string pinsFile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),"adws","windows-taskbar-pins.json");
    private readonly Form panel;
    private readonly Win32Backend backend;
    private readonly FlowLayoutPanel tasks = new() { Dock = DockStyle.Fill, WrapContents = false, AutoScroll = true };
    private readonly List<Form> backgrounds = [];
    private readonly StartMenu menu;
    private readonly Button start = new() { Text = "ADWS  开始", Dock = DockStyle.Left, Width = 112 };
    private readonly WiriBridge? wiri;
    private HashSet<long> managedIds = [];
    private bool querying;
    private string taskSignature = "";

    public DesktopSurface(Form host, HostConfig config, Win32Backend backend, Process guardian)
    {
        wiri = config.Wiri is { } settings ? new(settings) : null;
        this.config=config;
        try { if(File.Exists(pinsFile)) pins.AddRange(Wire.Decode<string[]>(File.ReadAllText(pinsFile))); }
        catch(Exception e) when(e is IOException or System.Text.Json.JsonException) { }
        panel = host;
        this.backend = backend;
        panel.Controls.Clear();
        panel.Text = "ADWS 桌面面板";
        panel.FormBorderStyle = FormBorderStyle.None;
        panel.StartPosition = FormStartPosition.Manual;
        panel.TopMost = true;
        panel.BackColor = Color.FromArgb(27, 36, 51);
        panel.Controls.Add(tasks);
        panel.Controls.Add(start);
        menu = new StartMenu(config, () =>
        {
            guardian.Refresh();
            Native.ShowWindowAsync(guardian.MainWindowHandle, 9);
            Native.SetForegroundWindow(guardian.MainWindowHandle);
        });
        start.Click += (_, _) => menu.Open(panel);
        panel.Shown += (_, _) => RebuildScreens();
        Microsoft.Win32.SystemEvents.DisplaySettingsChanged += DisplaysChanged;
    }

    private void DisplaysChanged(object? sender, EventArgs args)
    {
        if (panel.IsHandleCreated && !panel.IsDisposed) panel.BeginInvoke(RebuildScreens);
    }

    private async void RebuildScreens()
    {
        foreach (var background in backgrounds) background.Dispose();
        backgrounds.Clear();
        foreach (var screen in Screen.AllScreens)
        {
            var background = new Wallpaper { Bounds = screen.Bounds };
            if (screen.Primary) background.Controls.Add(new FileDesktop(config));
            background.Show();
            Native.SetWindowPos(background.Handle, 1, screen.Bounds.X, screen.Bounds.Y,
                screen.Bounds.Width, screen.Bounds.Height, 0x10);
            backgrounds.Add(background);
        }
        var area = Screen.PrimaryScreen!.WorkingArea;
        int height = 52 * panel.DeviceDpi / 96;
        panel.Bounds = new Rectangle(area.Left, area.Bottom - height, area.Width, height);
        if (wiri is not null) { try { await wiri.Reserve(height); } catch (Exception e) { panel.Text = "ADWS · " + e.Message; } }
    }

    public Rectangle TileArea(Rectangle area) => area.IntersectsWith(panel.Bounds)
        ? Rectangle.FromLTRB(area.Left, area.Top, area.Right, Math.Max(area.Top + 1, panel.Top)) : area;

    public async void UpdateTasks()
    {
        if (querying) return;
        var list = backend.Snapshot(tasks: true);
        var managed = new HashSet<long>();
        if (wiri is not null)
        {
            querying = true;
            try
            {
                var remote = await wiri.Windows();
                foreach (var w in remote) managed.Add(w.Id);
                list = remote.Concat(list).DistinctBy(w => w.Id).OrderBy(w => w.Id).ToArray();
            }
            catch (Exception e) { panel.Text = "ADWS · " + e.Message; }
            finally { querying = false; }
            if (tasks.IsDisposed || panel.IsDisposed) return;
        }
        managedIds = managed;
        foreach(var gone in paths.Keys.Except(list.Select(w=>w.ProcessId)).ToArray()) paths.Remove(gone);
        string App(WindowInfo w)
        {
            if(paths.TryGetValue(w.ProcessId,out var path)) return path;
            try { using var process=Process.GetProcessById((int)w.ProcessId); path=process.MainModule?.FileName; }
            catch(Exception e) when(e is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception) { }
            return paths[w.ProcessId]=path ?? $"PID {w.ProcessId}";
        }
        var groups=list.GroupBy(App,StringComparer.OrdinalIgnoreCase).ToDictionary(g=>g.Key,g=>g.ToArray(),StringComparer.OrdinalIgnoreCase);
        var keys=pins.Concat(groups.Keys).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        var signature=Wire.Encode(new { keys, pins, windows=list.Select(w=>new {w.Id,w.ProcessId,w.Title,w.Focused,managed=managed.Contains(w.Id)}) });
        if(signature==taskSignature)return;
        taskSignature=signature;
        tasks.SuspendLayout();
        foreach(var key in buttons.Keys.Except(keys,StringComparer.OrdinalIgnoreCase).ToArray())
        { buttons[key].ContextMenuStrip?.Dispose(); buttons[key].Dispose(); buttons.Remove(key); }
        foreach(var key in keys)
        {
            var members=groups.GetValueOrDefault(key) ?? [];
            if(!buttons.TryGetValue(key,out var button))
            {
                buttons[key]=button=new Button {Width=180,Height=36,AutoEllipsis=true};
                button.Click+=(_,_)=>{
                    if(button.Tag is not WindowInfo[] live)return;
                    if(live.Length==0) Program.Report(()=>Program.Start(new(key,[])).Dispose());
                    else if(live.Length==1) _=Activate(live[0]);
                    else button.ContextMenuStrip?.Show(button,new Point(0,0),ToolStripDropDownDirection.AboveRight);
                };
                tasks.Controls.Add(button);
            }
            button.Tag=members;
            button.Text=members.Length==1 ? members[0].Title : Path.GetFileNameWithoutExtension(key)+(members.Length>1?$" ({members.Length})":"");
            button.AccessibleName=button.Text;
            button.BackColor=members.Any(w=>w.Focused)?Color.LightSkyBlue:Color.WhiteSmoke;
            if(button.ContextMenuStrip?.Visible!=true)
            {
                button.ContextMenuStrip?.Dispose();var popup=new ContextMenuStrip();
                foreach(var w in members)popup.Items.Add(w.Title,null,async (_,_)=>await Activate(w));
                if(File.Exists(key))popup.Items.Add(pins.Contains(key)?"取消固定":"固定到任务栏",null,(_,_)=>Program.Report(()=>
                {
                    if(!pins.Remove(key))pins.Add(key);
                    Directory.CreateDirectory(Path.GetDirectoryName(pinsFile)!);
                    File.WriteAllText(pinsFile+".tmp",Wire.Encode(pins));File.Move(pinsFile+".tmp",pinsFile,true); taskSignature=""; UpdateTasks();
                }));
                button.ContextMenuStrip=popup;
            }
            tasks.Controls.SetChildIndex(button,Array.IndexOf(keys,key));
        }
        async Task Activate(WindowInfo w)
        {
            if(wiri is not null && managedIds.Contains(w.Id)){try{await wiri.Focus(w.Id);}catch(Exception e){MessageBox.Show(e.Message,"ADWS · wiri");}}
            else if(!backend.Focus(w))System.Media.SystemSounds.Beep.Play();
        }
        tasks.ResumeLayout();
    }

    public void Dispose()
    {
        Microsoft.Win32.SystemEvents.DisplaySettingsChanged -= DisplaysChanged;
        foreach (var background in backgrounds) background.Dispose();
        menu.Dispose();
    }

    private sealed class Wallpaper : Form
    {
        public Wallpaper()
        {
            Text = "ADWS 桌面背景";
            StartPosition = FormStartPosition.Manual;
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            DoubleBuffered = true;
        }
        protected override bool ShowWithoutActivation => true;
        protected override CreateParams CreateParams
        {
            get { var cp = base.CreateParams; cp.ExStyle |= 0x80; return cp; }
        }
        protected override void WndProc(ref Message m)
        {
            if (m.Msg == 0x46 && m.LParam != 0)
                System.Runtime.InteropServices.Marshal.WriteIntPtr(m.LParam, IntPtr.Size, (nint)1);
            base.WndProc(ref m);
        }
        protected override void OnPaintBackground(PaintEventArgs e)
        {
            using var brush = new LinearGradientBrush(ClientRectangle, Color.FromArgb(19, 35, 61),
                Color.FromArgb(54, 104, 109), 32f);
            e.Graphics.FillRectangle(brush, ClientRectangle);
        }
    }
}
