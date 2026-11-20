import os, socket, tempfile, pathlib, platform, subprocess, time
with tempfile.TemporaryDirectory(prefix="pr5-extra-",dir="/var/tmp") as root:
    path=pathlib.Path(root)
    mount=subprocess.check_output(["findmnt","-n","-T",root,"-o","SOURCE,FSTYPE"],text=True).strip()
    print("filesystem",mount,"kernel",platform.release(),flush=True)
    assert mount.split()[-1]=="ext4"
    owner=path/"owner"; temp=path/"owner.tmp"; moved=path/"held"
    # The private fixture inserts a listening socket at the metadata destination.
    with socket.socket(socket.AF_UNIX) as listening:
        listening.bind(str(owner)); listening.listen()
        pin=os.open(owner,os.O_PATH|os.O_NOFOLLOW)
        temp.write_text("marker")
        os.replace(temp,owner)
        print("replace_metadata_removes_injected_socket_name",owner.is_file(),
              "pinned_socket_nlink",os.fstat(pin).st_nlink)
        assert os.fstat(pin).st_nlink==0
        os.close(pin)
    owner.write_text("previous")
    pin=os.open(owner,os.O_PATH|os.O_NOFOLLOW)
    owner.rename(moved)
    # Reopening the retained regular inode never touches the new socket at owner.
    with socket.socket(socket.AF_UNIX) as listening:
        listening.bind(str(owner)); listening.listen()
        sock=owner.lstat()
        with open(f"/proc/self/fd/{pin}","r+b") as f:
            f.write(b"updated!"); f.truncate(); f.flush(); os.fsync(f.fileno())
        assert (sock.st_dev,sock.st_ino)==(owner.lstat().st_dev,owner.lstat().st_ino)
        assert moved.read_text()=="updated!"
        with socket.socket(socket.AF_UNIX) as client: client.connect(str(owner))
        print("pinned_regular_write_keeps_replacement_socket",True)
    os.close(pin)
    old=owner.lstat()
    time.sleep(.05)
    owner.rename(path/"moved.sock")
    new=(path/"moved.sock").lstat()
    print("delayed_rename_ctime_changed",old.st_ctime_ns!=new.st_ctime_ns)
    assert (old.st_dev,old.st_ino)==(new.st_dev,new.st_ino)
