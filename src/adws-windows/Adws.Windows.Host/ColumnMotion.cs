using System.Diagnostics;
using System.Runtime.InteropServices;

namespace Adws.Windows;

internal static class ColumnMotion
{
    [DllImport("gdi32.dll")] private static extern nint CreateRectRgn(int l,int t,int r,int b);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(nint handle);
    [DllImport("gdi32.dll")] private static extern int CombineRgn(nint dst,nint a,nint b,int mode);
    [DllImport("user32.dll")] private static extern int GetWindowRgn(nint hwnd,nint region);
    [DllImport("user32.dll")] private static extern int SetWindowRgn(nint hwnd,nint region,bool redraw);

    [DllImport("user32.dll")] private static extern nint BeginDeferWindowPos(int count);
    [DllImport("user32.dll")] private static extern nint DeferWindowPos(nint batch,nint hwnd,nint after,int x,int y,int width,int height,uint flags);
    [DllImport("user32.dll")] private static extern bool EndDeferWindowPos(nint batch);

    private sealed record Part(WindowInfo Window, Box Slot, int Start, nint Shape);
    public static async Task Play(Placement[] previous, Placement[] next, Box area, WindowInfo[] windows, Func<bool> cancelled)
    {
        if (previous.Length != 2 || next.Length != 2) return;
        int direction = previous[1].Id == next[0].Id ? 1 : previous[0].Id == next[1].Id ? -1 : 0;
        if (direction == 0) return;
        var shared = direction > 0 ? previous[1] : previous[0];
        int distance = next.First(p => p.Id == shared.Id).Bounds.X - shared.Bounds.X;
        var parts = new List<Part>();
        bool Valid(Part p)
        {
            Native.GetWindowThreadProcessId((nint)p.Window.Id, out uint pid);
            return pid == p.Window.ProcessId;
        }
        try
        {
            foreach (var placement in previous.Concat(next).DistinctBy(p => p.Id))
            {
                var w = windows.FirstOrDefault(w => w.Id == placement.Id);
                if (w is null) return;
                var shape = CreateRectRgn(0,0,0,0);
                if (shape == 0) return;
                if (GetWindowRgn((nint)w.Id, shape) == 0) { DeleteObject(shape); shape = 0; }
                var old = previous.FirstOrDefault(p => p.Id == w.Id);
                parts.Add(new(w,placement.Bounds,old?.Bounds.X ?? placement.Bounds.X-distance,shape));
            }
            var clock = Stopwatch.StartNew();
            while (!cancelled())
            {
                double t = Math.Min(1,clock.Elapsed.TotalMilliseconds / 420);
                int offset = (int)Math.Round(distance * t*t*(3-2*t));
                var frames = new List<(nint Handle,int X,int Width)>();
                foreach (var part in parts)
                {
                    if (!Valid(part)) continue;
                    int x = part.Start + offset;
                    int width = part.Slot.Width;
                    var clip = CreateRectRgn(Math.Clamp(area.X-x,0,width),0,
                        Math.Clamp(area.X+area.Width-x,0,width),area.Height);
                    if (clip == 0) return;
                    if (part.Shape != 0) CombineRgn(clip,clip,part.Shape,1);
                    var hwnd = (nint)part.Window.Id;
                    if (SetWindowRgn(hwnd,clip,false) == 0) { DeleteObject(clip); return; }
                    frames.Add((hwnd,x,width));
                }
                var batch = BeginDeferWindowPos(frames.Count);
                if (batch == 0) return;
                foreach (var frame in frames)
                {
                    batch = DeferWindowPos(batch,frame.Handle,0,frame.X,area.Y,frame.Width,area.Height,0x14);
                    if (batch == 0) return;
                }
                if (!EndDeferWindowPos(batch)) return;
                if (t >= 1) break;
                await Task.Delay(12);
            }
        }
        finally
        {
            foreach (var part in parts)
            {
                if (Valid(part))
                {
                    var target = next.FirstOrDefault(p => p.Id == part.Window.Id);
                    var bounds = target?.Bounds ?? part.Slot;
                    // Park the outgoing column behind its visible neighbor before removing the clip.
                    Native.SetWindowPos((nint)part.Window.Id,target is null ? (nint)next[^1].Id : 0,
                        bounds.X,bounds.Y,bounds.Width,bounds.Height,target is null ? 0x10u : 0x14u);
                    if (SetWindowRgn((nint)part.Window.Id,part.Shape,true) != 0) continue;
                }
                if (part.Shape != 0) DeleteObject(part.Shape);
            }
        }
    }
}
