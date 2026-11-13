using System.Diagnostics;
using System.Text;

namespace Adws.Windows;

internal sealed class WmClient : IDisposable
{
    private Process? process;
    private ProcessJob? job;
    internal int? ChildId => process?.Id;
    public async Task<Placement[]> Arrange(CommandSpec command, LayoutRequest request)
    {
        try
        {
            if (process is null || process.HasExited)
            {
                Dispose();
                var info = command.StartInfo();
                info.RedirectStandardInput = info.RedirectStandardOutput = info.RedirectStandardError = true;
                info.StandardInputEncoding = info.StandardOutputEncoding = new UTF8Encoding(false);
                info.CreateNoWindow = true;
                process = Process.Start(info) ?? throw new IOException("WM failed to start");
                job = new ProcessJob();
                job.Attach(process);
                // Drain stderr without retaining unbounded module output.
                _ = DrainErrors(process.StandardError.BaseStream);
            }
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            var payload = Wire.Encode(request);
            if (Encoding.UTF8.GetByteCount(payload) > Wire.MaxBytes) throw new InvalidDataException("Snapshot too large");
            await process.StandardInput.WriteLineAsync(payload.AsMemory(), deadline.Token);
            await process.StandardInput.FlushAsync(deadline.Token);
            var reply = await Wire.ReadLineAsync(process.StandardOutput, deadline.Token);
            return TilePolicy.Validate(request, Wire.Decode<LayoutReply>(reply));
        }
        catch { Dispose(); throw; }
    }

    private static async Task DrainErrors(Stream stream)
    {
        try { await stream.CopyToAsync(Stream.Null); }
        catch (IOException) { }
        catch (ObjectDisposedException) { }
    }

    public void Dispose()
    {
        if (process is null) return;
        try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
        catch (InvalidOperationException) { }
        finally { job?.Dispose(); job = null; process.Dispose(); process = null; }
    }
}
