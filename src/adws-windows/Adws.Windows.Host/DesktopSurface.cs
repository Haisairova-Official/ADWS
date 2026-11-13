using System.Diagnostics;
using System.Drawing.Drawing2D;

namespace Adws.Windows;

internal sealed class DesktopSurface : IDisposable
{
    private readonly Form panel;
    private readonly Win32Backend backend;
    private readonly FlowLayoutPanel tasks = new() { Dock = DockStyle.Fill, WrapContents = false, AutoScroll = true };
    private readonly List<Form> backgrounds = [];
    private readonly StartMenu menu;
    private readonly Button start = new() { Text = "ADWS  开始", Dock = DockStyle.Left, Width = 112 };
    private string taskSignature = "";

    public DesktopSurface(Form host, HostConfig config, Win32Backend backend, Process guardian)
    {
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

    private void RebuildScreens()
    {
        foreach (var background in backgrounds) background.Dispose();
        backgrounds.Clear();
        foreach (var screen in Screen.AllScreens)
        {
            var background = new Wallpaper { Bounds = screen.Bounds };
            background.Show();
            Native.SetWindowPos(background.Handle, 1, screen.Bounds.X, screen.Bounds.Y,
                screen.Bounds.Width, screen.Bounds.Height, 0x10);
            backgrounds.Add(background);
        }
        var area = Screen.PrimaryScreen!.WorkingArea;
        int height = 52 * panel.DeviceDpi / 96;
        panel.Bounds = new Rectangle(area.Left, area.Bottom - height, area.Width, height);
    }

    public Rectangle TileArea(Rectangle area) => area.IntersectsWith(panel.Bounds)
        ? Rectangle.FromLTRB(area.Left, area.Top, area.Right, Math.Max(area.Top + 1, panel.Top)) : area;

    public void UpdateTasks()
    {
        var list = backend.Snapshot(tasks: true);
        var signature = Wire.Encode(list.Select(w => new { w.Id, w.ProcessId, w.Title, w.Focused }));
        if (signature == taskSignature) return;
        taskSignature = signature;
        tasks.SuspendLayout();
        while (tasks.Controls.Count > 0) tasks.Controls[0].Dispose();
        foreach (var w in list)
        {
            var button = new Button { Text = w.Title, Width = 180, Height = 36, AutoEllipsis = true,
                AccessibleName = w.Title, BackColor = w.Focused ? Color.LightSkyBlue : Color.WhiteSmoke };
            button.Click += (_, _) => { if (!backend.Focus(w)) System.Media.SystemSounds.Beep.Play(); };
            tasks.Controls.Add(button);
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
            get { var cp = base.CreateParams; cp.ExStyle |= 0x08000080; return cp; }
        }
        protected override void WndProc(ref Message m)
        {
            if (m.Msg == 0x21) { m.Result = 3; return; }
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
