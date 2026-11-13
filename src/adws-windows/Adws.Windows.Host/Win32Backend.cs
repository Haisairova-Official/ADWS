using System.ComponentModel;
using System.Text;

namespace Adws.Windows;

// All methods, hook registration and disposal run on the Host UI/message-loop thread.
internal sealed class Win32Backend : IDisposable
{
    private readonly Native.EventProc callback;
    private readonly List<nint> hooks = [];
    public uint? OnlyProcessId { get; set; }
    public event Action? Changed;
    public Win32Backend()
    {
        callback = (_, kind, hwnd, obj, child, _, _) =>
        {
            if (hwnd != 0 && (kind < 0x8000 || (obj == 0 && child == 0))) Changed?.Invoke();
        };
        try
        {
            // Foreground, move/size end, minimize start/end; create/destroy/show/hide.
            foreach (var range in new (uint, uint)[] { (3, 3), (0xB, 0xB), (0x16, 0x17), (0x8000, 0x8003), (0x800C, 0x800C) })
            {
                nint hook = Native.SetWinEventHook(range.Item1, range.Item2, 0, callback, 0, 0, 2);
                if (hook == 0) throw new Win32Exception("Cannot install WinEvent hook");
                hooks.Add(hook);
            }
        }
        catch { Dispose(); throw; }
    }

    public WindowInfo[] Snapshot()
    {
        var result = new List<WindowInfo>();
        Native.EnumWindows((hwnd, _) =>
        {
            Native.GetWindowThreadProcessId(hwnd, out uint pid);
            if (OnlyProcessId.HasValue && pid != OnlyProcessId.Value) return true;
            if (pid == Environment.ProcessId || !Native.IsWindowVisible(hwnd) || Native.IsIconic(hwnd) ||
                Native.GetWindow(hwnd, 4) != 0) return true; // Owned dialogs float.
            long style = Native.GetWindowLongPtr(hwnd, -16).ToInt64();
            long exStyle = Native.GetWindowLongPtr(hwnd, -20).ToInt64();
            if ((exStyle & (0x80 | 0x08000000)) != 0 || (style & 0x40000) == 0) return true;
            if (Native.DwmGetWindowAttribute(hwnd, 14, out int cloaked, sizeof(int)) != 0 || cloaked != 0) return true;
            var name = new StringBuilder(256);
            Native.GetClassName(hwnd, name, name.Capacity);
            if (name.ToString() is "Progman" or "WorkerW" or "Shell_TrayWnd" or "Shell_SecondaryTrayWnd") return true;
            var title = new StringBuilder(1024);
            Native.GetWindowText(hwnd, title, title.Capacity);
            if (title.Length == 0 || !Native.GetWindowRect(hwnd, out var r)) return true;
            var screen = Screen.FromHandle(hwnd).Bounds;
            // Fullscreen/maximized windows are left alone in this MVP.
            if ((style & 0x01000000) != 0 || ((style & 0x00C00000) == 0 && r.Left <= screen.Left && r.Top <= screen.Top &&
                r.Right >= screen.Right && r.Bottom >= screen.Bottom)) return true;
            result.Add(new(hwnd.ToInt64(), pid, title.ToString(), new(r.Left, r.Top, r.Right - r.Left, r.Bottom - r.Top),
                hwnd == Native.GetForegroundWindow()));
            return true;
        }, 0);
        return result.OrderBy(w => w.Id).ToArray();
    }

    public bool Move(WindowInfo expected, Box box)
    {
        nint hwnd = (nint)expected.Id;
        Native.GetWindowThreadProcessId(hwnd, out uint pid);
        if (!Native.IsWindow(hwnd) || pid != expected.ProcessId || !Snapshot().Any(w => w.Id == expected.Id)) return false;
        // Never activate or change z-order. Revalidate recycled HWND/process identity.
        return Native.SetWindowPos(hwnd, 0, box.X, box.Y, box.Width, box.Height, 0x0014 | 0x0400);
    }

    public bool Focus(WindowInfo expected)
    {
        nint hwnd = (nint)expected.Id;
        Native.GetWindowThreadProcessId(hwnd, out uint pid);
        return pid == expected.ProcessId && Native.IsWindowVisible(hwnd) && Native.SetForegroundWindow(hwnd);
    }

    public void Dispose()
    {
        foreach (nint hook in hooks) Native.UnhookWinEvent(hook);
        hooks.Clear();
        GC.KeepAlive(callback);
    }
}
