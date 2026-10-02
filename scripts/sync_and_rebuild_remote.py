import os
import tarfile
import tempfile
import paramiko

def main():
    print("[1/5] Archiving local frontend H5 dist...")
    dist_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frontend', 'laoyouji-app', 'dist', 'build', 'h5')
    temp_tar = os.path.join(tempfile.gettempdir(), 'frontend_h5.tar.gz')
    with tarfile.open(temp_tar, 'w:gz') as tar:
        for root, dirs, files in os.walk(dist_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, dist_dir)
                tar.add(full_path, arcname=rel_path)
    print(f"Archive created at {temp_tar} ({os.path.getsize(temp_tar)} bytes)")

    print("[2/5] Connecting to remote server 159.75.94.149...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('159.75.94.149', port=22, username='xiaoyuyu', password='Wsxy8829', timeout=20)
    
    print("[3/5] Uploading frontend archive...")
    sftp = ssh.open_sftp()
    sftp.put(temp_tar, '/home/xiaoyuyu/frontend_h5.tar.gz')
    sftp.close()
    print("Upload complete!")

    print("[4/5] Pulling latest git code & updating static_dist & restarting service...")
    update_cmd = (
        "echo Wsxy8829 | sudo -S bash -c '"
        "cd /opt/laoyouji && "
        "git pull origin yyy && "
        "mkdir -p /opt/laoyouji/backend/static_dist && "
        "tar -xzf /home/xiaoyuyu/frontend_h5.tar.gz -C /opt/laoyouji/backend/static_dist/ && "
        "chown -R root:root /opt/laoyouji/backend/static_dist && "
        "systemctl restart laoyouji"
        "'"
    )
    stdin, stdout, stderr = ssh.exec_command(update_cmd, get_pty=True)
    for line in stdout:
        try:
            print(line, end='')
        except UnicodeEncodeError:
            print(line.encode('ascii', 'replace').decode(), end='')

    print("\n[5/5] Rebuilding APK with build_apk.sh...")
    build_cmd = (
        "echo Wsxy8829 | sudo -S bash -c '"
        "cd /opt/laoyouji && "
        "./build_apk.sh"
        "'"
    )
    stdin, stdout, stderr = ssh.exec_command(build_cmd, get_pty=True)
    for line in stdout:
        try:
            print(line, end='')
        except UnicodeEncodeError:
            print(line.encode('ascii', 'replace').decode(), end='')

    print("\nVerifying APK build artifact...")
    stdin, stdout, stderr = ssh.exec_command("ls -lh /opt/laoyouji/backend/static_dist/laoyouji.apk ; cat /opt/laoyouji/backend/static_dist/version.json")
    for line in stdout:
        try:
            print(line, end='')
        except UnicodeEncodeError:
            print(line.encode('ascii', 'replace').decode(), end='')

    ssh.close()
    print("\n[SUCCESS] Server and APK synchronization completed successfully!")

if __name__ == '__main__':
    main()
