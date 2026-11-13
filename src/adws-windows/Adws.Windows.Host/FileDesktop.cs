using System.Diagnostics;
using System.Runtime.InteropServices;

namespace Adws.Windows;

// Native icon view provides Ctrl/Shift selection, drag rectangle and keyboard navigation.
internal sealed class FileDesktop : ListView
{
    private readonly HostConfig config;
    private readonly string root = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
    private string current;
    private readonly ImageList icons = new() { ImageSize = new(32,32), ColorDepth = ColorDepth.Depth32Bit };
    private readonly FileSystemWatcher watcher = new();
    private readonly System.Windows.Forms.Timer refresh = new() { Interval = 400 };
    private readonly ContextMenuStrip actions = new();
    public FileDesktop(HostConfig config)
    {
        this.config=config; current=root;
        Dock=DockStyle.Fill; View=View.LargeIcon; MultiSelect=true; HideSelection=false; BorderStyle=BorderStyle.None;
        BackColor=Color.FromArgb(28,53,69); ForeColor=Color.White; LargeImageList=icons;
        AccessibleName="桌面文件"; Alignment=ListViewAlignment.Left;
        actions.Items.Add("打开",null,(_,_)=>Open());
        actions.Items.Add("返回桌面",null,(_,_)=>Navigate(root));
        actions.Items.Add("刷新",null,(_,_)=>Reload());
        ContextMenuStrip=actions;
        ItemActivate+=(_,_)=>Open();
        KeyDown+=(_,e)=>{if(e.KeyCode==Keys.F5) Reload(); if(e.KeyCode==Keys.Back && current!=root) Navigate(Directory.GetParent(current)?.FullName ?? root);};
        watcher.NotifyFilter=NotifyFilters.FileName|NotifyFilters.DirectoryName;
        watcher.Created+=(_,_)=>Queue(); watcher.Deleted+=(_,_)=>Queue(); watcher.Renamed+=(_,_)=>Queue();
        refresh.Tick+=(_,_)=>{refresh.Stop();Reload();};
        HandleCreated+=(_,_)=>Navigate(root);
    }
    private void Queue() { if (!IsDisposed) { refresh.Stop(); refresh.Start(); } }
    private void Navigate(string path) => Program.Report(() =>
    {
        if (!Directory.Exists(path)) return;
        watcher.EnableRaisingEvents=false; watcher.SynchronizingObject=this;
        watcher.Path=path; current=path; watcher.EnableRaisingEvents=true; Reload();
    });
    private void Open() => Program.Report(() =>
    {
        if(SelectedItems.Count!=1 || SelectedItems[0].Tag is not string path) return;
        if(Directory.Exists(path))
        {
            if(config.FileManager is { } manager) Program.Start(manager with { Arguments=[..manager.Arguments,path] }).Dispose();
            else Navigate(path);
        }
        else Process.Start(new ProcessStartInfo(path){UseShellExecute=true})?.Dispose();
    });
    private void Reload()
    {
        var selected=SelectedItems.Cast<ListViewItem>().Select(i=>i.Tag as string).ToHashSet();
        BeginUpdate();
        try
        {
            var entries=new DirectoryInfo(current).EnumerateFileSystemInfos()
                .Where(f=>(f.Attributes & (FileAttributes.Hidden|FileAttributes.System))==0)
                .OrderByDescending(f=>f is DirectoryInfo).ThenBy(f=>f.Name,StringComparer.CurrentCultureIgnoreCase).ToArray();
            Items.Clear(); icons.Images.Clear(); _ = icons.Handle;
            foreach(var file in entries)
            {
                var info=new ShellInfo();
                ShellIcon(file.FullName,0,ref info,(uint)Marshal.SizeOf<ShellInfo>(),0x100);
                int index=-1;
                if(info.Icon!=0)
                {
                    try { using var icon=(Icon)Icon.FromHandle(info.Icon).Clone(); icons.Images.Add(icon); index=icons.Images.Count-1; }
                    finally { DestroyIcon(info.Icon); }
                }
                var item=Items.Add(file.Name,index); item.Tag=file.FullName; item.Selected=selected.Contains(file.FullName);
            }
        }
        catch(Exception e) when(e is IOException or UnauthorizedAccessException) { AccessibleDescription=e.Message; }
        finally { EndUpdate(); }
    }
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)]
    private struct ShellInfo
    {
        public nint Icon; public int IconIndex; public uint Attr;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=260)] public string Name;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=80)] public string Type;
    }
    [DllImport("shell32",EntryPoint="SHGetFileInfoW",CharSet=CharSet.Unicode)] private static extern nint ShellIcon(string path,uint attr,ref ShellInfo info,uint size,uint flags);
    [DllImport("user32")] private static extern bool DestroyIcon(nint icon);
    protected override void Dispose(bool disposing){if(disposing){watcher.Dispose();refresh.Dispose();actions.Dispose();icons.Dispose();}base.Dispose(disposing);}
}
