using System.Diagnostics;
using System.Text.Json;

namespace Adws.Windows;

// wiri is a standalone daemon with its own IPC, not a JSON-lines policy module.
internal sealed class WiriBridge(WiriConfig config)
{
    private string Binary(string name) => Path.GetFullPath(Path.Combine(config.Directory,name), AppContext.BaseDirectory);
    private Process? owned;

    private async Task<string> Call(params string[] arguments)
    {
        var command = new CommandSpec(Binary("wiri-ctl.exe"), ["-t","1","-j",..arguments]).StartInfo();
        command.CreateNoWindow = true;
        command.RedirectStandardOutput = command.RedirectStandardError = true;
        using var p = Process.Start(command) ?? throw new IOException("Cannot start wiri-ctl");
        var output = p.StandardOutput.ReadToEndAsync();
        var error = p.StandardError.ReadToEndAsync();
        using var timeout = new CancellationTokenSource(2500);
        try { await p.WaitForExitAsync(timeout.Token).ConfigureAwait(false); }
        catch (OperationCanceledException) { if (!p.HasExited) p.Kill(); throw new IOException("wiri IPC timed out"); }
        var json = await output.ConfigureAwait(false);
        if (p.ExitCode != 0) throw new IOException((await error.ConfigureAwait(false)).Trim());
        using var reply = JsonDocument.Parse(json);
        if (!reply.RootElement.GetProperty("success").GetBoolean()) throw new IOException("wiri rejected command: " + arguments[0]);
        return json;
    }

    public async Task Connect()
    {
        try { await Call("windows").ConfigureAwait(false); return; }
        catch (IOException) when (Process.GetProcessesByName("wiri").Length == 0) { }
        var info = new CommandSpec(Binary("wiri.exe"), ["--no-tray","--config",Path.GetFullPath(config.ConfigFile,AppContext.BaseDirectory)]).StartInfo();
        info.CreateNoWindow = true;
        owned = Process.Start(info) ?? throw new IOException("Cannot start wiri");
        for (int i=0;i<8 && !owned.HasExited;i++)
        {
            try { await Call("windows").ConfigureAwait(false); return; }
            catch (IOException) { await Task.Delay(180).ConfigureAwait(false); }
        }
        throw new IOException("wiri did not become ready");
    }

    public void Disconnect()
    {
        if (owned is null) return; // An already-running session belongs to its original caller.
        try { if (!owned.HasExited) Call("quit").GetAwaiter().GetResult(); }
        finally { owned.Dispose(); owned=null; }
    }
    public Task Reserve(int height) => Call("reserve-area","bottom",height.ToString());
    public Task Focus(long id) => Call("focus-window",id.ToString());
    public async Task<WindowInfo[]> Windows()
    {
        using var doc = JsonDocument.Parse(await Call("windows"));
        return doc.RootElement.GetProperty("result").GetProperty("windows").EnumerateArray()
            .Select(w => new WindowInfo(w.GetProperty("id").GetInt64(),w.GetProperty("pid").GetUInt32(),
                w.GetProperty("title").GetString() ?? "",new(0,0,0,0),w.GetProperty("is_focused").GetBoolean())).ToArray();
    }
}
