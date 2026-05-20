using IronOcr;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://+:5050");
var app = builder.Build();

// Activate license once at startup (no-op if key is empty — trial watermark applies).
// IronSuite keys use IronSoftware.License; standalone IronOCR keys use IronOcr.License.
var licenseKey = (Environment.GetEnvironmentVariable("IRONOCR_LICENSE_KEY") ?? "").Trim();
if (!string.IsNullOrWhiteSpace(licenseKey))
    License.LicenseKey = licenseKey;

app.MapGet("/health", () => "ok");

app.MapPost("/ocr", async (OcrRequest req) =>
{
    if (string.IsNullOrWhiteSpace(req.ImageBase64))
        return Results.BadRequest(new { error = "imageBase64 is required" });

    byte[] imageBytes;
    try
    {
        imageBytes = Convert.FromBase64String(req.ImageBase64);
    }
    catch
    {
        return Results.BadRequest(new { error = "invalid base64" });
    }

    var ocr = new IronTesseract
    {
        Language = OcrLanguage.ThaiBest
     };
     ocr.AddSecondaryLanguage(OcrLanguage.EnglishBest);
     ocr.AddSecondaryLanguage(OcrLanguage.ThaiAlphabetBest);


    using var input = new OcrInput();
    using var ms = new MemoryStream(imageBytes);
    input.LoadImage(ms);

    var result = await Task.Run(() => ocr.Read(input));

    return Results.Ok(new
    {
        text = result.Text,
        confidence = result.Confidence / 100.0
    });
});

app.Run();

record OcrRequest(string ImageBase64);
