# requires powershell and .NET 4+. see https://chocolatey.org/install for more info.

$chocoVersion = powershell choco -v
if(-not($chocoVersion)){
    Write-Output "Chocolatey is not installed, installing now"
    Write-Output "IF YOU KEEP GETTING THIS MESSAGE ON EVERY BUILD, TRY RESTARTING THE GITLAB RUNNER SO IT GETS CHOCO INTO IT'S ENV"
    Set-ExecutionPolicy Bypass -Scope Process -Force; iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))
}
else{
    Write-Output "Chocolatey version $chocoVersion is already installed"
}