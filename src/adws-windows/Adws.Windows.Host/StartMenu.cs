using System.Diagnostics;
using System.Text.Json;

namespace Adws.Windows;

internal sealed class StartMenu : Form
{
    private sealed record Entry(string Name, string Id, Action Run)
    {
        public override string ToString() => Name;
    }

    private readonly TextBox search = new() { Dock = DockStyle.Top, PlaceholderText = "搜索应用或输入程序路径", AccessibleName = "搜索应用" };
    private readonly ListBox results = new() { Dock = DockStyle.Fill, IntegralHeight = false, AccessibleName = "应用列表" };
    private readonly List<Entry> apps = [];
    private readonly HostConfig config;
    private readonly Dictionary<string, int> pins = new(StringComparer.OrdinalIgnoreCase);

    public StartMenu(HostConfig config, Action recover)
    {
        this.config = config;
        Text = "ADWS 开始菜单";
        FormBorderStyle = FormBorderStyle.FixedToolWindow;
        ControlBox = false;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.Manual;
        TopMost = true;
        KeyPreview = true;
        ClientSize = new(370, 420);
        var recovery = new Button { Text = "恢复控制台", Dock = DockStyle.Bottom };
        recovery.Click += (_, _) => { Hide(); recover(); };
        Controls.Add(results); Controls.Add(search); Controls.Add(recovery);
        search.TextChanged += (_, _) => Filter();
        results.MouseClick += (_, e) => { if (results.IndexFromPoint(e.Location) >= 0) Selected(); };
        KeyDown += (_, e) =>
        {
            if (e.KeyCode == Keys.Escape) Hide();
            else if (e.KeyCode == Keys.Down && search.Focused) { results.Focus(); if (results.Items.Count > 0) results.SelectedIndex = 0; }
            else if (e.KeyCode == Keys.Enter)
            {
                if (results.Focused) Selected();
                else if (search.Text.Trim().Length > 0) Run(() => Program.Start(new(search.Text.Trim().Trim('"'), [])).Dispose());
            }
            else return;
            e.SuppressKeyPress = true;
        };
        Deactivate += (_, _) => Hide();
        Add("终端", "adws.terminal", config.Terminal);
        Add("记事本", "adws.notepad", new("notepad.exe", []));
        if (config.FileManager is not null) Add("文件管理器", "adws.files", config.FileManager);
        Shown += async (_, _) =>
        {
            var catalog = await Task.Run(ReadCatalog);
            if (IsDisposed) return;
            apps.AddRange(catalog);
            Filter();
        };
    }

    private List<Entry> ReadCatalog()
    {
        var entries = new List<Entry>();
        var options = new EnumerationOptions { RecurseSubdirectories = true, IgnoreInaccessible = true, AttributesToSkip = FileAttributes.ReparsePoint };
        foreach (var folder in new[] { Environment.SpecialFolder.Programs, Environment.SpecialFolder.CommonPrograms })
        {
            string root = Environment.GetFolderPath(folder);
            if (!Directory.Exists(root)) continue;
            try
            {
                foreach (string file in Directory.EnumerateFiles(root, "*.lnk", options))
                    entries.Add(new(Path.GetFileNameWithoutExtension(file), Path.GetRelativePath(root, file).Replace('\\', '/'),
                        () => Process.Start(new ProcessStartInfo(file) { UseShellExecute = true })?.Dispose()));
            }
            catch (IOException) { }
        }
        return entries.DistinctBy(e => e.Id, StringComparer.OrdinalIgnoreCase).ToList();
    }

    private void Add(string name, string id, CommandSpec command) =>
        apps.Add(new(name, id, () => Program.Start(command).Dispose()));

    public void Open(Form panel)
    {
        if (Visible) { Hide(); return; }
        pins.Clear();
        var pinFile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "adws", "taskbar-pins.json");
        try
        {
            if (File.Exists(pinFile))
            {
                using var data = JsonDocument.Parse(File.ReadAllText(pinFile));
                if (data.RootElement.TryGetProperty("apps", out var list) && list.ValueKind == JsonValueKind.Array)
                    foreach (var item in list.EnumerateArray())
                        if (item.ValueKind == JsonValueKind.Object && item.TryGetProperty("desktop_id", out var id) && id.ValueKind == JsonValueKind.String)
                            pins.TryAdd(id.GetString()!, pins.Count);
            }
        }
        catch (Exception e) when (e is IOException or JsonException or UnauthorizedAccessException or InvalidOperationException) { }
        search.Clear(); Filter();
        Location = new(panel.Left, Math.Max(Screen.FromControl(panel).Bounds.Top, panel.Top - Height));
        Show(panel); Activate(); search.Focus();
    }

    private void Filter()
    {
        results.BeginUpdate(); results.Items.Clear();
        foreach (var app in apps.Where(a => a.Name.Contains(search.Text.Trim(), StringComparison.CurrentCultureIgnoreCase))
            .OrderBy(a => pins.GetValueOrDefault(a.Id, int.MaxValue)).ThenBy(a => !a.Id.StartsWith("adws.")).ThenBy(a => a.Name))
            results.Items.Add(app);
        results.EndUpdate();
    }
    private void Selected() { if (results.SelectedItem is Entry entry) Run(entry.Run); }
    private void Run(Action action) => Program.Report(() => { action(); Hide(); });
}
