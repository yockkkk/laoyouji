import paramiko
import sys

def main():
    print("Connecting to 159.75.94.149...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('159.75.94.149', port=22, username='xiaoyuyu', password='Wsxy8829', timeout=15)
    
    cmd = (
        "echo Wsxy8829 | sudo -S bash -c '"
        "cp -r /home/xiaoyuyu/static_dist_tmp/* /opt/laoyouji/backend/static_dist/ ; "
        "chown -R root:root /opt/laoyouji/backend/static_dist/ ; "
        "cd /opt/laoyouji ; "
        "./build_apk.sh"
        "'"
    )
    print("Executing remote copy and build_apk.sh...")
    stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    for line in stdout:
        print(line, end='', flush=True)
    
    print("\nChecking resulting APK file...")
    stdin, stdout, stderr = ssh.exec_command("ls -lh /opt/laoyouji/backend/static_dist/laoyouji.apk ; cat /opt/laoyouji/backend/static_dist/version.json")
    print(stdout.read().decode('utf-8', errors='ignore'))
    ssh.close()
    print("Build complete!")

if __name__ == '__main__':
    main()
