using System.Diagnostics;

namespace Adws.Windows;

internal static class ColumnDemo
{
    public static void Run(bool smooth)
    {
        var area = Screen.PrimaryScreen!.WorkingArea;
        var box = new Box(area.X + area.Width / 10, area.Y + area.Height / 6, area.Width * 8 / 10, area.Height * 2 / 3);
        var forms = new List<Form>();
        using var wm = new WmClient();
        foreach (char name in "ABC")
        {
            var form = new Form { Text = "ADWS · " + name, StartPosition = FormStartPosition.Manual,
                Bounds = new Rectangle(box.X, box.Y, box.Width / 2, box.Height),
                BackColor = name == 'A' ? Color.Teal : name == 'B' ? Color.SlateBlue : Color.SteelBlue };
            form.Controls.Add(new Label { Text = name.ToString(), Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
                ForeColor = Color.White, Font = new Font("Segoe UI", 72) });
            forms.Add(form);
            form.Show();
        }
        using var timer = new System.Windows.Forms.Timer { Interval = 2800 };
        var last = Array.Empty<Placement>();
        int page = 0;
        long seq = 0;
        bool closing = false;
        async Task Render()
        {
            timer.Stop();
            try
            {
                var items = forms.Select((f,i) => new WindowInfo(f.Handle, (uint)Environment.ProcessId, f.Text,
                    new Box(f.Left,f.Top,f.Width,f.Height), i == (page == 0 ? 0 : 2))).ToArray();
                var command = new CommandSpec(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),"dotnet","dotnet.exe"),
                    [Path.Combine(AppContext.BaseDirectory,"Adws.Windows.Wm.dll"),"--columns"]);
                var next = await wm.Arrange(command, new(1,++seq,"layout",["move-resize"],box,items));
                if (closing) return;
                foreach (var f in forms) if (!next.Any(p => p.Id == f.Handle)) f.SendToBack();
                if (!smooth || last.Length == 0)
                    foreach (var p in next) forms.Single(f => f.Handle == p.Id).BringToFront();
                if (smooth) await ColumnMotion.Play(last,next,box,items,() => closing);
                if (closing) return;
                foreach (var p in next) forms.Single(f => f.Handle == p.Id).Bounds = new(p.Bounds.X,p.Bounds.Y,p.Bounds.Width,p.Bounds.Height);
                last = next; page = 1-page; timer.Start();
            }
            catch (Exception e) { if (!closing) { MessageBox.Show(e.Message); forms[0].Close(); } }
        }
        foreach (var f in forms) f.FormClosed += (_,_) => { closing = true; timer.Stop(); Application.ExitThread(); };
        timer.Tick += async (_,_) => await Render();
        forms[0].BeginInvoke(async () => await Render());
        Application.Run();
        closing = true;
        foreach (var f in forms) f.Dispose();
    }
}
