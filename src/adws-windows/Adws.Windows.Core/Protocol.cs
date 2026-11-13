using System.Text;
using System.Text.Json;

namespace Adws.Windows;

public record Box(int X, int Y, int Width, int Height);
public record WindowInfo(long Id, uint ProcessId, string Title, Box Bounds, bool Focused);
public record Placement(long Id, Box Bounds);
// This is a separate window-policy protocol, not a panel.text-v1 renderer.
public record LayoutRequest(int Api, long Sequence, string Type, string[] Capabilities,
    Box WorkArea, WindowInfo[] Windows);
public record LayoutReply(int Api, long Sequence, string Type, Placement[] Placements);

public static class Wire
{
    public const int MaxBytes = 1024 * 1024; // Same framing limit as Plugin API v1.
    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    public static string Encode<T>(T value) => JsonSerializer.Serialize(value, Json);
    public static T Decode<T>(string value) => JsonSerializer.Deserialize<T>(value, Json)
        ?? throw new InvalidDataException("Null protocol message");

    public static async Task<string> ReadLineAsync(StreamReader reader, CancellationToken ct)
    {
        var line = new StringBuilder();
        var buffer = new char[1];
        int bytes = 0;
        while (await reader.ReadAsync(buffer.AsMemory(), ct) != 0)
        {
            char c = buffer[0];
            if (c == '\n') return line.ToString().TrimEnd('\r');
            // Conservative for surrogate pairs; never admits more than 1 MiB UTF-8.
            bytes += c <= 0x7f ? 1 : c <= 0x7ff ? 2 : 3;
            if (bytes > MaxBytes) throw new InvalidDataException("Protocol line exceeds 1 MiB");
            line.Append(c);
        }
        throw new EndOfStreamException("WM closed stdout");
    }
}

public static class TilePolicy
{
    public static LayoutReply Arrange(LayoutRequest request)
    {
        if (request.Api != 1 || request.Type != "layout")
            throw new InvalidDataException("Unsupported policy request");
        var area = request.WorkArea;
        int n = request.Windows.Length;
        if (n > area.Width || area.Width < 1 || area.Height < 1)
            throw new InvalidDataException("Insufficient work area");
        var placements = request.Windows.Select((w, i) =>
        {
            int left = (int)((long)area.Width * i / n);
            int right = (int)((long)area.Width * (i + 1) / n);
            return new Placement(w.Id, new Box(area.X + left, area.Y, right - left, area.Height));
        }).ToArray();
        return new(1, request.Sequence, "layout", placements);
    }

    public static Placement[] Validate(LayoutRequest request, LayoutReply reply)
    {
        if (reply.Api != 1 || reply.Type != "layout" || reply.Sequence != request.Sequence || reply.Placements is null)
            throw new InvalidDataException("WM reply does not match request");
        var allowed = request.Windows.Select(w => w.Id).ToHashSet();
        var seen = new HashSet<long>();
        var a = request.WorkArea;
        foreach (var p in reply.Placements)
        {
            if (p is null || p.Bounds is null || !allowed.Contains(p.Id) || !seen.Add(p.Id))
                throw new InvalidDataException("Unknown or duplicate window");
            var b = p.Bounds;
            if (b.Width < 1 || b.Height < 1 || b.X < a.X || b.Y < a.Y ||
                (long)b.X + b.Width > (long)a.X + a.Width || (long)b.Y + b.Height > (long)a.Y + a.Height)
                throw new InvalidDataException("Placement outside work area");
        }
        return reply.Placements;
    }
}

public record CommandSpec(string FileName, string[] Arguments)
{
    public System.Diagnostics.ProcessStartInfo StartInfo()
    {
        if (string.IsNullOrWhiteSpace(FileName)) throw new InvalidDataException("Missing executable");
        var info = new System.Diagnostics.ProcessStartInfo(FileName) { UseShellExecute = false };
        foreach (var argument in Arguments) info.ArgumentList.Add(argument);
        return info;
    }
}

public record WiriConfig(string Directory, string ConfigFile);

public sealed class HostConfig
{
    public WiriConfig? Wiri { get; set; }
    public CommandSpec? Wm { get; set; }
    public CommandSpec Terminal { get; set; } = new("cmd.exe", []);
    public CommandSpec? FileManager { get; set; }
}
