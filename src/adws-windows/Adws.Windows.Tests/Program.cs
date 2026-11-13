using Adws.Windows;
using System.Diagnostics;
using System.Text;

if (args.Length > 0 && args[0] == "--module")
{
    string mode = args[1];
    if (mode == "stall") { await Task.Delay(Timeout.Infinite); return 0; }
    if (mode == "eof") return 0;
    if (mode == "oversize") { Console.Write(new string('x', Wire.MaxBytes + 1)); await Task.Delay(10000); return 0; }
    using var reader = new StreamReader(Console.OpenStandardInput());
    while (true)
    {
        string line;
        try { line = await Wire.ReadLineAsync(reader, CancellationToken.None); }
        catch (EndOfStreamException) { return 0; }
        if (mode == "invalid") { Console.WriteLine("{broken"); continue; }
        var request = Wire.Decode<LayoutRequest>(line);
        Console.WriteLine(Wire.Encode(TilePolicy.Arrange(request)));
    }
}

int passed = 0;
void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
async Task Test(string name, Func<Task> run)
{
    await run(); passed++; Console.WriteLine("PASS " + name);
}
Task Sync(Action action) { action(); return Task.CompletedTask; }
LayoutRequest Request(int count = 3) => new(1, 42, "layout", ["move-resize"], new(-1920, -100, 1919, 1080),
    Enumerable.Range(1, count).Select(i => new WindowInfo(i, (uint)i, "日本語 中文 🪟", new(0, 0, 100, 100), i == 1)).ToArray());
void Reject(Action action)
{
    try { action(); } catch (InvalidDataException) { return; }
    throw new Exception("Expected rejection");
}
CommandSpec Module(string mode) => new(Environment.ProcessPath!, ["--module", mode]);

await Test("layout covers negative-origin monitor without gaps or overlap", () => Sync(() =>
{
    for (int count = 0; count <= 200; count++)
    {
        var request = Request(count);
        var reply = TilePolicy.Arrange(request);
        TilePolicy.Validate(request, reply);
        Check(reply.Placements.Length == count, "Missing window");
        if (count == 0) continue;
        int x = request.WorkArea.X;
        foreach (var p in reply.Placements) { Check(p.Bounds.X == x, "Gap"); x += p.Bounds.Width; }
        Check(x == -1, "Wrong right edge");
    }
}));
await Test("reject stale version, sequence, duplicate and unknown HWND", () => Sync(() =>
{
    var request = Request(); var reply = TilePolicy.Arrange(request);
    Reject(() => TilePolicy.Validate(request, reply with { Api = 2 }));
    Reject(() => TilePolicy.Validate(request, reply with { Sequence = 0 }));
    Reject(() => TilePolicy.Validate(request, reply with { Placements = [reply.Placements[0], reply.Placements[0]] }));
    Reject(() => TilePolicy.Validate(request, reply with { Placements = [new(999, request.WorkArea)] }));
}));
await Test("reject overflow, outside bounds, zero size and impossible layout", () => Sync(() =>
{
    var request = Request(); var reply = TilePolicy.Arrange(request);
    foreach (var box in new Box[] { new(-1921, -100, 1, 1), new(0, 0, int.MaxValue, 1), new(-1920, -100, 0, 5) })
        Reject(() => TilePolicy.Validate(request, reply with { Placements = [new(1, box)] }));
    Reject(() => TilePolicy.Arrange(request with { WorkArea = new(0, 0, 2, 2) }));
}));
await Test("UTF-8 JSON round trip and arguments remain literal", () => Sync(() =>
{
    var request = Request();
    Check(Wire.Decode<LayoutRequest>(Wire.Encode(request)).Windows[0].Title == request.Windows[0].Title, "Unicode damaged");
    var info = new CommandSpec("tool.exe", ["a b", "& calc.exe", "中文"]).StartInfo();
    Check(!info.UseShellExecute && info.ArgumentList[1] == "& calc.exe", "Shell interpretation");
}));
await Test("bounded framing: CRLF, EOF, oversize and cancellation", async () =>
{
    using var input = new StreamReader(new MemoryStream(Encoding.UTF8.GetBytes("{}\r\n")));
    Check(await Wire.ReadLineAsync(input, CancellationToken.None) == "{}", "CRLF");
    try { await Wire.ReadLineAsync(input, CancellationToken.None); throw new Exception("Expected EOF"); }
    catch (EndOfStreamException) { }
    using var huge = new StreamReader(new MemoryStream(Encoding.UTF8.GetBytes(new string('x', Wire.MaxBytes + 1))));
    try { await Wire.ReadLineAsync(huge, CancellationToken.None); throw new Exception("Expected limit"); }
    catch (InvalidDataException) { }
});
await Test("WM process persistent round trip", async () =>
{
    using var wm = new WmClient();
    Check((await wm.Arrange(Module("valid"), Request())).Length == 3, "Roundtrip");
    Check((await wm.Arrange(Module("valid"), Request(2) with { Sequence = 43 })).Length == 2, "Second request");
});
int actualWmAt = Array.IndexOf(args, "--wm");
if (actualWmAt >= 0)
    await Test("published sample WM round trip", async () =>
    {
        using var wm = new WmClient();
        Check((await wm.Arrange(new CommandSpec("dotnet", [args[actualWmAt + 1]]), Request())).Length == 3, "Published WM");
    });
foreach (string mode in new[] { "stall", "eof", "invalid", "oversize" })
    await Test("WM failure containment and manual retry: " + mode, async () =>
    {
        using var wm = new WmClient();
        var watch = Stopwatch.StartNew();
        bool rejected = false;
        try { await wm.Arrange(Module(mode), Request()); }
        catch (Exception e) when (e is IOException or InvalidDataException or OperationCanceledException or System.Text.Json.JsonException)
        { rejected = true; }
        Check(rejected && watch.Elapsed < TimeSpan.FromSeconds(6), "Failure not bounded");
        Check((await wm.Arrange(Module("valid"), Request())).Length == 3, "Manual retry failed");
    });
await Test("disposing WM terminates owned child", async () =>
{
    var wm = new WmClient();
    await wm.Arrange(Module("valid"), Request());
    using var child = Process.GetProcessById(wm.ChildId!.Value);
    wm.Dispose();
    Check(child.WaitForExit(3000), "Orphan WM process");
});
await Test("column insertion, bounded navigation and removal", () => Sync(() =>
{
    var order = new ColumnOrder();
    var a = Request().Windows[0] with { Id = 30, Focused = true };
    var b = a with { Id = 50, Focused = false };
    var c = a with { Id = 10, Focused = false };
    order.Update([a,b]);
    Check(order.Update([c,b,a]).Select(w => w.Id).SequenceEqual(new long[]{30,10,50}), "new column position");
    Check(order.Neighbor([b,a,c], -1) is null, "wrapped at edge");
    Check(order.Neighbor([b,a,c], 1)?.Id == 10, "wrong neighbor");
    Check(order.Neighbor([b,a], 1)?.Id == 50, "closed column left a gap");
}));
await Test("viewport follows third column without resizing the first two", () => Sync(() =>
{
    var view = new ColumnViewport();
    var r = Request(2);
    var first = view.Arrange(r);
    var three = Request(3);
    Check(view.Arrange(three).Placements.SequenceEqual(first.Placements), "opening resized visible columns");
    three = three with { Windows = three.Windows.Select((w,i) => w with { Focused = i == 2 }).ToArray() };
    Check(view.Arrange(three).Placements.Select(p => p.Id).SequenceEqual(new long[]{2,3}), "viewport did not advance");
    Check(view.Arrange(r).Placements.SequenceEqual(first.Placements), "viewport did not return");
}));
Console.WriteLine($"{passed} checks passed; no desktop mutations performed.");
return 0;
