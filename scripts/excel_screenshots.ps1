<#
.SYNOPSIS
  Настоящие скриншоты листов Excel для docs/.

.DESCRIPTION
  Открывает книги через COM (только чтение, без добавления в «последние файлы»),
  снимает окно Excel функцией PrintWindow и обрезает кадр: от строки формул
  до ярлыков листов. Заголовок окна и лента (там видна учётная запись Office)
  в кадр не попадают. Опорная точка — цвет шапки таблицы (#1F4E78).
  Окно Excel на несколько секунд появится на экране.

.EXAMPLE
  .\scripts\excel_screenshots.ps1
#>
param(
    [string]$OutDir = "docs"
)

$ErrorActionPreference = "Stop"

$Shots = @(
    @{ Workbook = "docs\example_catalog_3pages.xlsx"; Sheet = "Товары"; Zoom = 100; Out = "excel_preview.png" },
    @{ Workbook = "docs\example_catalog_full.xlsx"; Sheet = "Сводка по категориям"; Zoom = 68; Out = "summary_preview.png" }
)
$HeaderColor = "1F4E78"

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Win32Capture {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);
}
"@
[void][Win32Capture]::SetProcessDPIAware()

function Get-Hex([System.Drawing.Bitmap]$bmp, [int]$x, [int]$y) {
    $c = $bmp.GetPixel($x, $y)
    return "{0:X2}{1:X2}{2:X2}" -f $c.R, $c.G, $c.B
}

function Get-WindowBitmap([IntPtr]$hwnd) {
    $rect = New-Object Win32Capture+RECT
    [void][Win32Capture]::GetWindowRect($hwnd, [ref]$rect)
    $bmp = New-Object System.Drawing.Bitmap ($rect.Right - $rect.Left), ($rect.Bottom - $rect.Top)
    $graphics = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $graphics.GetHdc()
    [void][Win32Capture]::PrintWindow($hwnd, $hdc, 2)  # PW_RENDERFULLCONTENT
    $graphics.ReleaseHdc($hdc)
    $graphics.Dispose()
    return $bmp
}

function Save-SheetArea([System.Drawing.Bitmap]$bmp, [string]$path) {
    $probeX = 150  # внутри столбца A и поля имени ячейки
    # 1. Верх шапки таблицы — первый пиксель цвета шапки.
    $headerTop = -1
    for ($y = 0; $y -lt $bmp.Height; $y++) {
        if ((Get-Hex $bmp $probeX $y) -eq $HeaderColor) { $headerTop = $y; break }
    }
    if ($headerTop -lt 0) { throw "Шапка таблицы не найдена на снимке" }
    # 2. Вверх от шапки: над буквами столбцов ищем поле строки формул —
    #    белую полосу высотой от 15 px — и берём её верхнюю границу.
    $top = 0
    $whiteRun = 0
    for ($y = $headerTop - 1; $y -gt 0; $y--) {
        if ((Get-Hex $bmp $probeX $y) -eq "FFFFFF") { $whiteRun++; continue }
        if ($whiteRun -ge 15) { $top = $y; break }
        $whiteRun = 0
    }
    # 3. Низ: снизу вверх пропускаем рамку окна и строку состояния до её верхней границы.
    $y = $bmp.Height - 1
    while ($y -gt $top -and (Get-Hex $bmp $probeX $y) -ne "F5F5F5") { $y-- }
    while ($y -gt $top -and (Get-Hex $bmp $probeX $y) -eq "F5F5F5") { $y-- }
    $bottom = $y
    # 4. Право: конец шапки таблицы плюс отступ; слева — первый столбец после рамки окна.
    $right = $bmp.Width - 1
    while ($right -gt 0 -and (Get-Hex $bmp $right ($headerTop + 3)) -ne $HeaderColor) { $right-- }
    $right = [Math]::Min($bmp.Width - 1, $right + 30)
    $left = 0
    while ($left -lt $probeX -and (Get-Hex $bmp $left ($headerTop + 3)) -eq "000000") { $left++ }
    $left += 1

    $area = New-Object System.Drawing.Rectangle $left, $top, ($right - $left), ($bottom - $top)
    $cropped = $bmp.Clone($area, $bmp.PixelFormat)
    $cropped.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $cropped.Dispose()
    Write-Host "Сохранено: $path ($($area.Width)x$($area.Height))"
}

New-Item -ItemType Directory -Force $OutDir | Out-Null
$excel = New-Object -ComObject Excel.Application
try {
    $excel.DisplayAlerts = $false
    $excel.Visible = $true
    foreach ($shot in $Shots) {
        $book = $excel.Workbooks.Open((Resolve-Path $shot.Workbook).Path, 0, $true)  # только чтение
        $sheet = $book.Worksheets.Item($shot.Sheet)
        $sheet.Activate()
        $window = $excel.ActiveWindow
        $window.Zoom = $shot.Zoom
        $window.ScrollRow = 1
        $window.ScrollColumn = 1
        $sheet.Range("A1").Select() | Out-Null
        Start-Sleep -Milliseconds 1500

        $bmp = Get-WindowBitmap ([IntPtr]$excel.Hwnd)
        try { Save-SheetArea $bmp (Join-Path $OutDir $shot.Out) } finally { $bmp.Dispose() }
        $book.Close($false)
    }
}
finally {
    $excel.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
}
