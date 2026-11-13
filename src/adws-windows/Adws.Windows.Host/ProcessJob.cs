using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace Adws.Windows;

// Kill owned children when the guardian/host dies, including a hung policy process.
internal sealed class ProcessJob : IDisposable
{
    private readonly SafeFileHandle handle;
    [StructLayout(LayoutKind.Sequential)]
    private struct BasicLimits
    {
        public long ProcessTime, JobTime;
        public uint Flags;
        public nuint MinWorkingSet, MaxWorkingSet;
        public uint ActiveProcessLimit;
        public nuint Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters { public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)]
    private struct ExtendedLimits
    {
        public BasicLimits Basic;
        public IoCounters Io;
        public nuint ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern SafeFileHandle CreateJobObjectW(nint attributes, nint name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(SafeFileHandle job, int infoClass, ref ExtendedLimits info, uint length);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(SafeFileHandle job, nint process);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool IsProcessInJob(nint process, nint job, out bool result);
    public ProcessJob()
    {
        handle = CreateJobObjectW(0, 0);
        var limits = new ExtendedLimits { Basic = new BasicLimits { Flags = 0x2000 } };
        if (handle.IsInvalid || !SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf<ExtendedLimits>()))
        {
            int error = Marshal.GetLastWin32Error(); handle.Dispose(); throw new Win32Exception(error);
        }
    }
    public void Attach(Process process)
    {
        if (!AssignProcessToJobObject(handle, process.Handle))
        {
            int error = Marshal.GetLastWin32Error();
            IsProcessInJob(process.Handle, 0, out bool childInJob);
            IsProcessInJob((nint)(-1), 0, out bool hostInJob);
            throw new Win32Exception(error, $"Cannot supervise WM: hostInJob={hostInJob}, childInJob={childInJob}, exited={process.HasExited}");
        }
    }
    public void Dispose() => handle.Dispose();
}
