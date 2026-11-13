using Adws.Windows;
using System.Text;

Console.InputEncoding = Console.OutputEncoding = new UTF8Encoding(false);
try
{
    using var input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false, true));
    var viewport = new ColumnViewport();
    while (true)
    {
        string line;
        try { line = await Wire.ReadLineAsync(input, CancellationToken.None); }
        catch (EndOfStreamException) { break; }
        var request = Wire.Decode<LayoutRequest>(line);
        Console.WriteLine(Wire.Encode(args.Contains("--columns") ? viewport.Arrange(request) : TilePolicy.Arrange(request)));
    }
    return 0;
}
catch (Exception e)
{
    Console.Error.WriteLine(e.Message);
    return 1;
}
