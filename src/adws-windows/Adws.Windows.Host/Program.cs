using System.Diagnostics;

namespace Adws.Windows;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        if (args.Contains("--fixture"))
        {
            var first = new Form { Text = "ADWS smoke window A", Bounds = new(100, 100, 350, 250) };
            var second = new Form { Text = "ADWS smoke window B", Bounds = new(300, 200, 350, 250) };
            first.Shown += (_, _) => second.Show();
            var lifetime = new System.Windows.Forms.Timer { Interval = 7000 };
            lifetime.Tick += (_, _) => { second.Close(); lifetime.Stop(); };
            lifetime.Start();
            Application.Run(first);
            lifetime.Dispose(); second.Dispose(); first.Dispose();
            return 0;
        }
        if (args.Contains("--inspect"))
        {
            // Read-only diagnostic: no hotkeys, moves, focus or application launches.
            using var backend = new Win32Backend();
            string json = Wire.Encode(backend.Snapshot());
            int index = Array.IndexOf(args, "--output");
            if (index < 0 || index + 1 >= args.Length) return 2;
            File.WriteAllText(args[index + 1], json);
            return 0;
        }
        if (!args.Contains("--test-session") && !args.Contains("--desktop"))
        {
            MessageBox.Show("ADWS Windows MVP: run --test-session only in a VM or dedicated test account. " +
                "No shell registration is performed. Use --inspect --output file.json for read-only diagnostics.");
            return 2;
        }
        string path = Path.Combine(AppContext.BaseDirectory, "windows-config.json");
        HostConfig config;
        try { config = File.Exists(path) ? Wire.Decode<HostConfig>(File.ReadAllText(path)) : new(); }
        catch (Exception e) { MessageBox.Show("Invalid configuration: " + e.Message); return 2; }
        if (args.Contains("--worker"))
        {
            int at = Array.IndexOf(args, "--heartbeat");
            int guardianAt = Array.IndexOf(args, "--guardian-pid");
            if (at < 0 || at + 1 >= args.Length || guardianAt < 0 || guardianAt + 1 >= args.Length) return 2;
            using var heartbeat = EventWaitHandle.OpenExisting(args[at + 1]);
            using var guardian = Process.GetProcessById(int.Parse(args[guardianAt + 1]));
            int scopeAt = Array.IndexOf(args, "--scope-pid");
            int reportAt = Array.IndexOf(args, "--report");
            uint? scope = scopeAt >= 0 ? uint.Parse(args[scopeAt + 1]) : null;
            string? report = reportAt >= 0 ? args[reportAt + 1] : null;
            Application.Run(new WorkerForm(config, heartbeat, guardian, scope, report, args.Contains("--desktop")));
        }
        else
        {
            using var single = new Mutex(true, "Local\\ADWS.Windows.Guardian", out bool created);
            if (!created) { MessageBox.Show("ADWS test host is already running."); return 2; }
            int reportAt = Array.IndexOf(args, "--report");
            Application.Run(new RecoveryForm(config, args.Contains("--smoke"),
                reportAt >= 0 ? args[reportAt + 1] : null, args.Contains("--desktop")));
        }
        return 0;
    }

    internal static Process Start(CommandSpec command) => Process.Start(command.StartInfo())
        ?? throw new IOException("Cannot start " + command.FileName);
    internal static CommandSpec Self(params string[] arguments) => new(Environment.ProcessPath
        ?? throw new IOException("Host path unavailable"), arguments);
    internal static void Report(Action action)
    {
        try { action(); } catch (Exception e) { MessageBox.Show(e.Message, "ADWS"); }
    }
}

internal sealed class RecoveryForm : Form
{
    private readonly HostConfig config;
    private readonly string eventName = "Local\\ADWS.Heartbeat." + Guid.NewGuid().ToString("N");
    private readonly EventWaitHandle heartbeat;
    private readonly System.Windows.Forms.Timer timer = new() { Interval = 1000 };
    private readonly Label status = new() { AutoSize = true };
    private Process? worker;
    private long lastBeat;
    private readonly bool smoke;
    private readonly string? report;
    private Process? fixture;
    private readonly long started = Environment.TickCount64;
    private readonly bool desktop;
    public RecoveryForm(HostConfig config, bool smoke = false, string? report = null, bool desktop = false)
    {
        this.config = config;
        this.desktop = desktop;
        this.smoke = smoke; this.report = report;
        Text = "ADWS — Recovery / 恢复";
        FormBorderStyle = FormBorderStyle.FixedToolWindow;
        Size = new(560, 270);
        StartPosition = FormStartPosition.CenterScreen;
        heartbeat = new(false, EventResetMode.AutoReset, eventName);
        var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown };
        Controls.Add(panel);
        panel.Controls.Add(status);
        Add(panel, "Start / restart ADWS", StartWorker);
        Add(panel, "Stop ADWS window management", StopWorker);
        Add(panel, "Open terminal", () => { using var p = Program.Start(config.Terminal); });
        Add(panel, "Task Manager", () => { using var p = Program.Start(new("taskmgr.exe", [])); });
        Add(panel, "Restore Explorer (manual)", () =>
        {
            StopWorker();
            using var p = Program.Start(new(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "explorer.exe"), []));
        });
        timer.Tick += (_, _) =>
        {
            if (smoke && Environment.TickCount64 - started >= 12000) { Close(); return; }
            if (heartbeat.WaitOne(0)) lastBeat = Environment.TickCount64;
            status.Text = worker is null ? "Management stopped; recovery is available." : worker.HasExited
                ? "Host exited. Restart manually or open a recovery tool."
                : Environment.TickCount64 - lastBeat > 10000 ? "Host unresponsive. Stop/restart is available."
                : "Host responsive. DWM remains the compositor.";
        };
        Shown += (_, _) => { Program.Report(StartWorker); if (desktop) WindowState = FormWindowState.Minimized; };
        timer.Start();
    }
    private static void Add(Control panel, string text, Action action)
    {
        var button = new Button { Text = text, AutoSize = true };
        button.Click += (_, _) => Program.Report(action);
        panel.Controls.Add(button);
    }
    private void StartWorker()
    {
        StopWorker();
        while (heartbeat.WaitOne(0)) { }
        lastBeat = Environment.TickCount64;
        var arguments = new List<string> { "--test-session", "--worker", "--heartbeat", eventName,
            "--guardian-pid", Environment.ProcessId.ToString() };
        if (smoke)
        {
            if (fixture is null) fixture = Program.Start(Program.Self("--fixture"));
            arguments.AddRange(["--scope-pid", fixture.Id.ToString()]);
            if (report is not null) arguments.AddRange(["--report", report]);
        }
        if (desktop) arguments.Add("--desktop");
        worker = Program.Start(Program.Self(arguments.ToArray()));
    }
    private void StopWorker()
    {
        if (worker is null) return;
        if (!worker.HasExited)
        {
            worker.CloseMainWindow();
            if (!worker.WaitForExit(2500)) worker.Kill(); // User-launched applications survive.
        }
        worker.Dispose(); worker = null;
    }
    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        // In an Explorer-free session closing this window must be deliberate.
        if (!smoke && MessageBox.Show("Exit ADWS and its recovery window? In a shell-only session, keep a terminal open first.",
            "ADWS", MessageBoxButtons.YesNo) != DialogResult.Yes) { e.Cancel = true; return; }
        StopWorker();
        if (fixture is not null)
        {
            if (!fixture.HasExited) fixture.Kill();
            fixture.Dispose(); fixture = null;
        }
        timer.Stop(); timer.Dispose(); heartbeat.Dispose();
        base.OnFormClosing(e);
    }
}

internal sealed class WorkerForm : Form
{
    private readonly HostConfig config;
    private readonly EventWaitHandle heartbeat;
    private readonly Process guardian;
    private readonly Win32Backend backend = new();
    private readonly WmClient wm = new();
    private readonly System.Windows.Forms.Timer timer = new() { Interval = 500 };
    private readonly ListBox windows = new() { Dock = DockStyle.Fill, DisplayMember = "Title" };
    private readonly Label status = new() { AutoSize = true };
    private readonly CheckBox automatic = new() { Text = "Automatic tiling (test session)", AutoSize = true };
    private readonly Dictionary<long, WindowInfo> originals = [];
    private bool dirty = true, busy, closing;
    private long sequence;
    private int ticks;
    private readonly string? smokeReport;
    private int eventCount, maxWindows, minWindows = int.MaxValue, layouts, moveFailures, focusAccepted;
    private string? lastError;
    private DesktopSurface? surface;
    public WorkerForm(HostConfig config, EventWaitHandle heartbeat, Process guardian, uint? scope = null, string? report = null, bool desktop = false)
    {
        this.config = config; this.heartbeat = heartbeat; this.guardian = guardian;
        backend.OnlyProcessId = scope; smokeReport = report;
        automatic.Checked = scope.HasValue;
        Text = "ADWS — Windows test host"; Size = new(700, 440);
        var actions = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true };
        Controls.Add(windows); Controls.Add(actions);
        Add(actions, "Tile", async () => await Tile());
        Add(actions, "Focus selected", () =>
        {
            if (windows.SelectedItem is WindowInfo w)
                status.Text = backend.Focus(w) ? "Focus requested" : "Windows denied foreground activation";
        });
        Add(actions, "Terminal", () => { using var p = Program.Start(config.Terminal); });
        Add(actions, "Files", () =>
        {
            using var p = Program.Start(config.FileManager ?? throw new InvalidOperationException("Configure an independent fileManager first."));
        });
        var executable = new TextBox { Width = 240, PlaceholderText = "Executable path (no shell command)" };
        actions.Controls.Add(executable);
        Add(actions, "Launch", () => { using var p = Program.Start(new(executable.Text, [])); });
        actions.Controls.Add(automatic); actions.Controls.Add(status);
        if (desktop) surface = new DesktopSurface(this, config, backend, guardian);
        backend.Changed += () => { dirty = true; eventCount++; };
        timer.Tick += async (_, _) =>
        {
            if (this.guardian.HasExited) { Close(); return; }
            heartbeat.Set();
            if (busy) return;
            if (++ticks % 10 == 0) dirty = true; // Reconcile missed events every five seconds.
            if (!dirty) return;
            dirty = false; RefreshWindows();
            if (automatic.Checked) await Tile();
        };
        Shown += (_, _) =>
        {
            // Ctrl+Alt+T: terminal; Ctrl+Alt+L: tile; Ctrl+Alt+J: next focus.
            foreach (var binding in new (int, uint)[] { (1, 0x54), (2, 0x4C), (3, 0x4A) })
                if (!Native.RegisterHotKey(Handle, binding.Item1, 0x4003, binding.Item2))
                    status.Text = "A shortcut is unavailable; buttons remain usable.";
            RefreshWindows(); timer.Start();
        };
    }
    private static void Add(Control parent, string text, Action action)
    {
        var button = new Button { Text = text, AutoSize = true };
        button.Click += (_, _) => Program.Report(action); parent.Controls.Add(button);
    }
    private WindowInfo[] RefreshWindows()
    {
        long? selected = (windows.SelectedItem as WindowInfo)?.Id;
        var snapshot = backend.Snapshot();
        if (backend.OnlyProcessId.HasValue)
        {
            maxWindows = Math.Max(maxWindows, snapshot.Length);
            if (maxWindows > 0) minWindows = Math.Min(minWindows, snapshot.Length);
        }
        windows.BeginUpdate(); windows.Items.Clear(); windows.Items.AddRange(snapshot);
        if (selected.HasValue) windows.SelectedItem = snapshot.FirstOrDefault(w => w.Id == selected);
        windows.EndUpdate(); surface?.UpdateTasks(); return snapshot;
    }
    private async Task Tile()
    {
        if (busy || closing) return;
        busy = true;
        try
        {
            var snapshot = RefreshWindows();
            WriteSmokeReport();
            var command = config.Wm ?? new CommandSpec(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "dotnet", "dotnet.exe"), [Path.Combine(AppContext.BaseDirectory, "Adws.Windows.Wm.dll")]);
            foreach (var group in snapshot.GroupBy(w => Screen.FromHandle((nint)w.Id).DeviceName))
            {
                var area = Screen.FromHandle((nint)group.First().Id).WorkingArea;
                if (surface is not null) area = surface.TileArea(area);
                var request = new LayoutRequest(1, ++sequence, "layout", ["enumerate", "move-resize", "focus-best-effort"],
                    new(area.X, area.Y, area.Width, area.Height), group.ToArray());
                var placements = await wm.Arrange(command, request);
                if (closing) return;
                int failed = 0;
                foreach (var p in placements)
                {
                    var before = group.First(w => w.Id == p.Id);
                    originals.TryAdd(before.Id, before);
                    if (!backend.Move(before, p.Bounds)) failed++;
                }
                status.Text = failed == 0 ? "Layout applied" : $"{failed} window(s) refused placement";
                if (backend.OnlyProcessId.HasValue)
                {
                    layouts++; moveFailures += failed;
                    if (backend.Focus(group.First())) focusAccepted++;
                    WriteSmokeReport();
                }
            }
        }
        catch (Exception e)
        {
            if (closing) return;
            lastError = e.ToString();
            WriteSmokeReport();
            automatic.Checked = false;
            status.Text = "WM stopped: " + e.Message + ". Tile retries manually.";
        }
        finally { busy = false; }
    }
    protected override void WndProc(ref Message m)
    {
        if (m.Msg == 0x0312)
        {
            switch (m.WParam.ToInt32())
            {
                case 1: Program.Report(() => { using var p = Program.Start(config.Terminal); }); break;
                case 2: _ = Tile(); break;
                case 3:
                    var items = backend.Snapshot();
                    if (items.Length > 0)
                    {
                        int index = Array.FindIndex(items, w => w.Focused);
                        backend.Focus(items[(index + 1) % items.Length]);
                    }
                    break;
            }
        }
        base.WndProc(ref m);
    }
    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        surface?.Dispose();
        closing = true; timer.Stop(); timer.Dispose();
        WriteSmokeReport();
        wm.Dispose();
        foreach (var original in originals.Values) backend.Move(original, original.Bounds);
        for (int id = 1; id <= 3; id++) Native.UnregisterHotKey(Handle, id);
        backend.Dispose(); base.OnFormClosed(e);
    }
    private void WriteSmokeReport()
    {
        if (smokeReport is null) return;
        File.WriteAllText(smokeReport, Wire.Encode(new { maxWindows, minWindows, eventCount, layouts, moveFailures, focusAccepted,
            scopedToFixture = backend.OnlyProcessId.HasValue, lastError,
            explorerRunning = Process.GetProcessesByName("explorer").Length > 0 }));
    }
}
