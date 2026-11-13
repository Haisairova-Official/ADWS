namespace Adws.Windows;

// Session order per output. A native handle is only meaningful with its process ID.
public sealed class ColumnOrder
{
    private readonly List<(long Id, uint Pid)> order = [];
    private (long Id, uint Pid)? active;
    public WindowInfo[] Update(WindowInfo[] snapshot)
    {
        var live = snapshot.ToDictionary(w => (w.Id, w.ProcessId));
        int previous = active is { } a ? order.IndexOf(a) : -1;
        order.RemoveAll(key => !live.ContainsKey(key));
        int cursor = active is { } anchor ? order.IndexOf(anchor) : -1;
        if (cursor < 0) cursor = previous < 0 ? order.Count - 1 : Math.Clamp(previous - 1, -1, order.Count - 1);
        foreach (var key in live.Keys)
            if (!order.Contains(key)) order.Insert(++cursor, key);
        var focused = snapshot.FirstOrDefault(w => w.Focused);
        if (focused is not null) active = (focused.Id, focused.ProcessId);
        else if (active is null || !order.Contains(active.Value))
            active = order.Count > 0 ? order[Math.Clamp(previous, 0, order.Count - 1)] : null;
        return order.Select(key => live[key]).ToArray();
    }

    public WindowInfo? Neighbor(WindowInfo[] snapshot, int direction)
    {
        var windows = Update(snapshot);
        if (active is null || windows.Length == 0) return null;
        int i = order.IndexOf(active.Value) + direction;
        return i >= 0 && i < windows.Length ? windows[i] : null;
    }
}

public sealed class ColumnViewport
{
    private readonly Dictionary<Box, (long Id, uint Pid)> left = [];
    public LayoutReply Arrange(LayoutRequest request)
    {
        var windows = request.Windows;
        var area = request.WorkArea;
        if (windows.Length == 0) return new(1, request.Sequence, "layout", []);
        int slots = area.Width >= 2 ? 2 : 1;
        left.TryGetValue(area, out var previous);
        int first = Math.Max(0, Array.FindIndex(windows, w => (w.Id,w.ProcessId) == previous));
        int focus = Array.FindIndex(windows, w => w.Focused);
        if (focus >= 0 && focus < first) first = focus;
        if (focus >= first + slots) first = focus - slots + 1;
        first = Math.Min(first, Math.Max(0, windows.Length - slots));
        left[area] = (windows[first].Id, windows[first].ProcessId);
        var placements = new List<Placement>();
        for (int i = first; i < Math.Min(first + slots, windows.Length); i++)
        {
            int x = area.Width * (i - first) / slots;
            int end = (int)((long)area.Width * (i - first + 1) / slots);
            placements.Add(new(windows[i].Id, new(area.X + x, area.Y, end - x, area.Height)));
        }
        return new(1, request.Sequence, "layout", placements.ToArray());
    }
}
