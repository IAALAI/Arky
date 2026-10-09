import 'frida-il2cpp-bridge';
import Java from 'frida-java-bridge';

const hosts = new Set([
  'ak-conf.hypergryph.com', 'launcher.hypergryph.com', 'as.hypergryph.com',
  'user.hypergryph.com', 'ak-gs-gf.hypergryph.com', 'ak-as.hypergryph.com',
  'binding-service.hypergryph.com', 'ak.hypergryph.com',
]);
const status = {managed: false, java: false, errors: []};

// Match the local-client compatibility layer used by the working Waydroid
// baseline. These optional SDK modules reject an instrumented debug process.
// A failed load returns NULL rather than a handle belonging to another library.
const loader = Module.findGlobalExportByName('android_dlopen_ext');
if (loader !== null) {
  const originalLoader = new NativeFunction(loader, 'pointer', ['pointer', 'int', 'pointer']);
  Interceptor.replace(loader, new NativeCallback((path, flags, extension) => {
    const name = path.isNull() ? '' : path.readUtf8String();
    if (/(?:libmsaoaidsec|libanogs)\.so$/.test(name)) {
      send({type: 'sdk-compatibility', library: name.split('/').pop()});
      return ptr(0);
    }
    return originalLoader(path, flags, extension);
  }, 'pointer', ['pointer', 'int', 'pointer']));
}

function gameUrl(value) {
  const text = String(value);
  const match = /^https:\/\/([^/:]+)(?::\d+)?(\/.*)?$/i.exec(text);
  return match && hosts.has(match[1].toLowerCase())
    ? 'http://' + match[1] + (match[2] || '/') : text;
}

rpc.exports = {
  status() { return status; },
  route(value) { return gameUrl(value); },
};

// Apply debugging changes in this application's memory. APK and resource
// files remain exactly as shipped; CDN URLs are never redirected to the game API.
Java.perform(() => {
  const URL = Java.use('java.net.URL');
  const constructor = URL.$init.overload('java.lang.String');
  constructor.implementation = function (value) {
    return constructor.call(this, gameUrl(value));
  };
  for (const name of ['okhttp3.Request$Builder', 'com.android.okhttp.Request$Builder']) {
    try {
      const builder = Java.use(name);
      const url = builder.url.overload('java.lang.String');
      url.implementation = function (value) { return url.call(this, gameUrl(value)); };
    } catch (_) {}
  }
  status.java = true;
  send({type: 'ready', scope: 'java'});
});

Il2Cpp.perform(() => {
  try {
    const crypt = Il2Cpp.domain.assembly('Assembly-CSharp').image.class('Torappu.CryptUtils');
    crypt.method('VerifySignMD5RSA').overload('System.String', 'System.String', 'System.String')
      .implementation = () => true;
    const rsa = Il2Cpp.domain.assembly('mscorlib').image.class('System.Security.Cryptography.RSACryptoServiceProvider');
    rsa.method('VerifyHash').overload('System.Byte[]', 'System.String', 'System.Byte[]')
      .implementation = () => true;
    const verify = Il2Cpp.domain.assembly('Torappu.Common').image
      .class('Torappu.Network.Certificate.CertificateHandlerFactory')
      .nested('BouncyCastleCertVerifyer')
      .method('IsValid').overload('System.Uri', 'Org.BouncyCastle.Asn1.X509.X509CertificateStructure[]');
    verify.implementation = function (uri, certificates) {
      if (hosts.has(uri.method('get_Host').invoke().content)) return !certificates.isNull();
      return this.method('IsValid').invoke(uri, certificates);
    };
    status.managed = true;
    send({type: 'ready', scope: 'managed'});
  } catch (error) {
    status.errors.push(String(error));
    send({type: 'hook-error', message: String(error)});
  }
});
