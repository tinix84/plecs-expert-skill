# shot_window.ps1 - capture one window (by title substring) to PNG with PrintWindow (works when covered, not when minimised)
param([Parameter(Mandatory)][string]$Title, [Parameter(Mandatory)][string]$Png)
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices; using System.Text;
public static class W {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public static IntPtr Find(string part) { IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => { var sb = new StringBuilder(512); GetWindowText(h, sb, 512);
      if (IsWindowVisible(h) && sb.ToString().IndexOf(part, StringComparison.OrdinalIgnoreCase) >= 0) { found = h; return false; } return true; }, IntPtr.Zero);
    return found; }
  public static string List() { var o = new StringBuilder();
    EnumWindows((h, l) => { var sb = new StringBuilder(512); GetWindowText(h, sb, 512); if (IsWindowVisible(h) && sb.Length > 0) o.AppendLine(sb.ToString()); return true; }, IntPtr.Zero);
    return o.ToString(); }
}
'@
$h = [W]::Find($Title)
if ($h -eq [IntPtr]::Zero) { "window not found: $Title"; [W]::List() | Select-String -Pattern 'PLECS|plecs|reconstructed'; return }
if ([W]::IsIconic($h)) { [W]::ShowWindow($h, 9) | Out-Null; Start-Sleep -Milliseconds 800 }
$r = New-Object W+RECT; [W]::GetWindowRect($h, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
$g = [Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc(); [W]::PrintWindow($h, $dc, 2) | Out-Null; $g.ReleaseHdc($dc); $g.Dispose()
$bmp.Save($Png, [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
"saved $Png ($($r.R - $r.L) x $($r.B - $r.T))"
