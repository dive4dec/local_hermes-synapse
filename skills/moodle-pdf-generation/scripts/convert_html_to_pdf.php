<?php
// Convert a self-contained Moodle quiz-preview HTML to PDF via dompdf.
// Pure-PHP, no browser, no root. Reproduces the browser print far better than TCPDF
// (which overlaps markdown-rendered objects with manual Cell()/Rect() elements).
//
// Usage:
//   php convert_html_to_pdf.php <input.html> <output.pdf>
//
// dompdf is installed by install_deps.sh into $HERMES_HOME/lib/dompdf/

$dompdf_autoload = getenv('HERMES_HOME') . '/lib/dompdf/vendor/autoload.php';
if (!file_exists($dompdf_autoload)) {
    // Fall back to local vendor/ if present (skill-dir relative)
    $dompdf_autoload = __DIR__ . '/vendor/autoload.php';
}
if (!file_exists($dompdf_autoload)) {
    fwrite(STDERR, "dompdf not found. Run scripts/install_deps.sh first.\n");
    fwrite(STDERR, "Expected: $dompdf_autoload\n");
    exit(1);
}
require_once($dompdf_autoload);

use Dompdf\Dompdf;
use Dompdf\Options;

if ($argc < 3) {
    fwrite(STDERR, "Usage: php convert_html_to_pdf.php <input.html> <output.pdf>\n");
    exit(1);
}

$in  = $argv[1];
$out = $argv[2];

if (!file_exists($in)) { fwrite(STDERR, "Input not found: $in\n"); exit(1); }

$html = file_get_contents($in);

$options = new Options();
$options->set('isRemoteEnabled', false);
$options->set('isHtml5ParserEnabled', true);
$options->set('defaultFont', 'DejaVu Sans');
$options->set('dpi', 96);
$options->set('defaultMediaType', 'print'); // apply @media print rules from the HTML

$dompdf = new Dompdf($options);
$dompdf->loadHtml($html, 'UTF-8');
$dompdf->setPaper('A4', 'portrait');
$dompdf->render();
file_put_contents($out, $dompdf->output());

echo "PDF written: $out\n";
echo "Bytes: " . filesize($out) . "\n";
