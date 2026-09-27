"""Build the experimental x86 MCS bridge; no downloads, injection or policy changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='cl', help='x86 MSVC cl (CI), or a Windows x86 TinyCC compiler')
    parser.add_argument('--output', type=Path, default=Path.home()/'.local/share/mcpywrap/mcs-auth-bridge')
    parser.add_argument('--sign-thumbprint', help='Sign with this existing CurrentUser/My code-signing certificate')
    parser.add_argument('--sign-only', action='store_true', help='Sign an existing, verified build without recompiling')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This build requires Windows')
    source = Path(__file__).resolve().parent.parent/'native/mcs_auth'
    compiler = Path(shutil.which(args.cc) or args.cc).resolve()
    csc = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework/v4.0.30319/csc.exe'
    if not args.sign_only and (not compiler.is_file() or not csc.is_file()):
        parser.error('Both an x86 C compiler and .NET Framework C# compiler must exist')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    public = json.loads((source/'publisher.json').read_text(encoding='utf-8-sig'))
    if hashlib.sha256((source/'publisher.cer').read_bytes()).hexdigest() != public['certificate_sha256']:
        parser.error('Pinned publisher certificate does not match')
    sources = {p.name: hashlib.sha256(p.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
               for p in sorted(source.iterdir()) if p.suffix in ('.cs', '.c')}
    if args.sign_only:
        previous = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
        if previous['sources'] != sources or any(hashlib.sha256((output/name).read_bytes()).hexdigest() != digest
                                                for name, digest in previous['files'].items()):
            parser.error('Build changed before signing')
    else:
        subprocess.run([str(csc), '/nologo', '/target:library', '/platform:x86',
                        '/reference:System.Web.Extensions.dll', '/out:'+str(output/'McpyMcsAuth.dll'),
                        str(source/'Bridge.cs')], check=True)
        subprocess.run([str(csc), '/nologo', '/platform:x86', '/reference:System.Web.Extensions.dll',
                        '/out:'+str(output/'Injector.exe'), str(source/'Injector.cs')], check=True)
        if compiler.name.lower() in ('cl', 'cl.exe'):
            if os.environ.get('VSCMD_ARG_TGT_ARCH') != 'x86':
                parser.error('Use an x86 MSVC developer environment')
            subprocess.run([str(compiler), '/nologo', '/LD', '/MT', '/O2', '/W4', '/utf-8',
                            str(source/'Loader.c'), '/Fo'+str(output/'Loader.obj'),
                            '/link', '/OUT:'+str(output/'Loader.dll')], cwd=output, check=True)
        else:
            subprocess.run([str(compiler), '-shared', str(source/'Loader.c'), '-o', str(output/'Loader.dll')], check=True)
        shutil.copyfile(source/'publisher.cer', output/'publisher.cer')
    if args.sign_thumbprint:
        if args.sign_thumbprint.upper() != public['thumbprint']:
            parser.error('Signing key does not match the pinned publisher')
        environment = dict(os.environ, MCPY_BUILD_OUTPUT=str(output), MCPY_SIGN_THUMBPRINT=args.sign_thumbprint)
        environment = {k: v for k, v in environment.items() if k.casefold() != 'psmodulepath'}
        script = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$cert=Get-Item -LiteralPath ('Cert:\CurrentUser\My\'+$env:MCPY_SIGN_THUMBPRINT)
if(!$cert.HasPrivateKey -or $cert.NotAfter -le (Get-Date)) {throw 'Signing certificate unavailable or expired'}
foreach($name in @('Injector.exe','Loader.dll','McpyMcsAuth.dll')) {
 $file=Join-Path $env:MCPY_BUILD_OUTPUT $name
 $null=Set-AuthenticodeSignature -LiteralPath $file -Certificate $cert -HashAlgorithm SHA256
 $signature=Get-AuthenticodeSignature -LiteralPath $file
 if($signature.SignerCertificate.Thumbprint -ne $cert.Thumbprint -or $signature.Status -in @('HashMismatch','NotSigned','NotSupportedFileFormat')) {throw 'Signing failed'}
}
$null=Export-Certificate -Cert $cert -FilePath (Join-Path $env:MCPY_BUILD_OUTPUT 'publisher.cer')
@{thumbprint=$cert.Thumbprint;subject=$cert.Subject;expires=$cert.NotAfter.ToUniversalTime().ToString('o')} | ConvertTo-Json -Compress
'''
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], env=environment,
                                capture_output=True, encoding='utf-8-sig')
        if result.returncode:
            raise SystemExit('Signing failed: '+result.stderr.strip())
        signed = json.loads(result.stdout)
        if signed['thumbprint'] != public['thumbprint']:
            parser.error('Unexpected signer')
        print('Signed bridge and public certificate built at:', output)
    else:
        print('Unsigned bridge built at:', output)
    manifest = dict(public, bridge_version=1, signed=bool(args.sign_thumbprint), sources=sources)
    manifest['files'] = {name: hashlib.sha256((output/name).read_bytes()).hexdigest()
                         for name in ('Injector.exe', 'Loader.dll', 'McpyMcsAuth.dll', 'publisher.cer')}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('No certificate trust or security policy was changed.')


if __name__ == '__main__':
    main()
