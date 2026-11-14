param([string]$Title = 'UIA TEST FORM')
# A tiny test window (WinForms). Its TITLE mirrors its state so a test can read what really happened.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$f = New-Object Windows.Forms.Form
$f.Text = "$Title | clicks=0 text= agree=False combo="
$f.Width = 520; $f.Height = 360; $f.StartPosition = 'Manual'
$off = if ($Title -like 'OTHER*') { 640 } else { 80 }
$f.Location = New-Object Drawing.Point($off, 80)

$tb = New-Object Windows.Forms.TextBox; $tb.Location = '20,20'; $tb.Width = 300; $tb.AccessibleName = 'Name box'
$btn = New-Object Windows.Forms.Button; $btn.Text = 'Go'; $btn.Location = '20,60'; $btn.AccessibleName = 'Go'
$chk = New-Object Windows.Forms.CheckBox; $chk.Text = 'Agree'; $chk.Location = '20,100'; $chk.AccessibleName = 'Agree'
$cmb = New-Object Windows.Forms.ComboBox; $cmb.Location = '20,140'; $cmb.Width = 200; $cmb.AccessibleName = 'Choice'
$cmb.DropDownStyle = 'DropDownList'; [void]$cmb.Items.AddRange(@('alpha', 'beta', 'gamma'))
$ro = New-Object Windows.Forms.TextBox; $ro.Location = '20,180'; $ro.Width = 300; $ro.ReadOnly = $true; $ro.Text = 'read only'; $ro.AccessibleName = 'Locked box'
$f.Controls.AddRange(@($tb, $btn, $chk, $cmb, $ro))

$script:n = 0
$update = { $f.Text = "$Title | clicks=$script:n text=$($tb.Text) agree=$($chk.Checked) combo=$($cmb.Text)" }
$btn.Add_Click({ $script:n++; & $update })
$tb.Add_TextChanged($update); $chk.Add_CheckedChanged($update); $cmb.Add_SelectedIndexChanged($update)
$f.Add_Shown({ $f.Activate() })
[void]$f.ShowDialog()
