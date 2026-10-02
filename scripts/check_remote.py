import paramiko

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('159.75.94.149', port=22, username='xiaoyuyu', password='Wsxy8829', timeout=10)
    cmd = "echo Wsxy8829 | sudo -S cat /opt/laoyouji/build_apk.sh"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    print("OUTPUT:\n", stdout.read().decode())
    ssh.close()

if __name__ == '__main__':
    main()
