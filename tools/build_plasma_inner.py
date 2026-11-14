from pathlib import Path
import subprocess,os,json,shutil,time
p=Path('/diag');s=p/'source/plasma-mobile-6.7.5';b=p/'build';logs=p/'logs';locked=json.loads(Path('/device/rootfs/plasma/inputs.json').read_text())
# Keep Fedora's existing hardening convention without rebuilding another environment.
flags='-O2 -g -fexceptions -Wall -Werror=format-security -Wp,-U_FORTIFY_SOURCE,-D_FORTIFY_SOURCE=3 -Wp,-D_GLIBCXX_ASSERTIONS -fstack-protector-strong -mbranch-protection=standard -fasynchronous-unwind-tables -fstack-clash-protection -fno-omit-frame-pointer -mno-omit-leaf-frame-pointer'
link='-Wl,-z,relro -Wl,--as-needed -Wl,-z,pack-relative-relocs -Wl,-z,now -Wl,--build-id=sha1'
for k in ['CFLAGS','CXXFLAGS']:os.environ[k]=flags
os.environ['LDFLAGS']=link
commands=[['cmake','-S',str(s),'-B',str(b),'-DBUILD_TESTING=OFF','-DBUILD_QCH=OFF','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_FLAGS_RELEASE=-DNDEBUG','-DCMAKE_CXX_FLAGS_RELEASE=-DNDEBUG','-DCMAKE_INSTALL_PREFIX=/usr','-DKDE_INSTALL_LIBDIR=/usr/lib64','-DKDE_INSTALL_LIBEXECDIR=/usr/libexec','-DKDE_INSTALL_PLUGINDIR=/usr/lib64/qt6/plugins','-DKDE_INSTALL_QMLDIR=/usr/lib64/qt6/qml','-DKDE_INSTALL_USE_QT_SYS_PATHS=ON'],['cmake','--build',str(b),'--target','org.kde.plasma.mobile.panel','org.kde.plasma.mobile.taskpanel','--parallel','2','--verbose']]
(p/'commands.json').write_text(json.dumps({'CFLAGS':flags,'CXXFLAGS':flags,'LDFLAGS':link,'argv':commands},indent=2)+'\n')
with (logs/'toolchain.log').open('w') as f:
 for argv in [['g++','--version'],['cmake','--version'],['pkg-config','--modversion','Qt6Qml','Qt6Quick']]:subprocess.run(argv,stdout=f,stderr=subprocess.STDOUT,check=True)
for name,argv in zip(['configure','build'],commands):
 start=time.time()
 with (logs/(name+'.log')).open('w') as f:r=subprocess.run(argv,stdout=f,stderr=subprocess.STDOUT)
 (p/(name+'-result.json')).write_text(json.dumps({'exit':r.returncode,'elapsed_seconds':time.time()-start},indent=2)+'\n')
 if r.returncode:raise SystemExit(r.returncode)
 if name=='configure':
  for relative,mtime in locked['generated_mtime_ns'].items():os.utime(b/relative,ns=(mtime,mtime))
for name in ['panel','taskpanel']:
 matches=list(b.rglob('org.kde.plasma.mobile.'+name+'.so'));assert len(matches)==1,matches
 output=p/'outputs'/matches[0].name;shutil.copy2(matches[0],output)
 subprocess.run(['strip','--strip-debug',str(output)],check=True)
print('TWO_PANEL_TARGETS_BUILT')
