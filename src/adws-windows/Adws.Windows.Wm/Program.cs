using Adws.Windows;
using System.Text;

Console.InputEncoding = Console.OutputEncoding = new UTF8Encoding(false);
try
{
    using var input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false, true));
    while (true)
    {
        string line;
        try { line = await Wire.ReadLineAsync(input, CancellationToken.None); }
        catch (EndOfStreamException) { break; }
        Console.WriteLine(Wire.Encode(TilePolicy.Arrange(Wire.Decode<LayoutRequest>(line))));
    }
    return 0;
}
catch (Exception e)
{
    Console.Error.WriteLine(e.Message);
    return 1;
}
