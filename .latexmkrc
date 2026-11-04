# LaTeXmk configuration for Overleaf / VS Code LaTeX Workshop
# Automatically routes compilation artifacts to build/ and ensures SyncTeX jump works flawlessly.

$pdf_mode = 1;
$out_dir = 'build';
$aux_dir = 'build';

# Post-compilation hook: copy synctex.gz from build/ to project root so VS Code can locate it for forward/reverse jump
$success_cmd = 'cmd /c copy /y build\%R.synctex.gz .';
