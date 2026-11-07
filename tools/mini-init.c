/*
 * Phase-0 initramfs init for the evert 4.19 forward-port.
 * Build as a static ARM64 executable for the initramfs.
 * A userspace marker does not validate individual drivers.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef MINI_INIT_BUILD_ID
#define MINI_INIT_BUILD_ID "unspecified"
#endif

static int kmsg_fd = -1;

static ssize_t write_retry(int fd, const void *buf, size_t size)
{
	ssize_t n;

	do {
		n = write(fd, buf, size);
	} while (n < 0 && errno == EINTR);
	return n;
}

static void log_msg(const char *fmt, ...)
{
	char msg[768];
	char out[sizeof(msg) + 3];
	const char truncated[] = "...[truncated]\n";
	va_list ap;
	int saved_errno = errno;
	int n;
	size_t len;
	ssize_t written;

	va_start(ap, fmt);
	n = vsnprintf(msg, sizeof(msg), fmt, ap);
	va_end(ap);
	if (n <= 0)
		goto done;

	len = (size_t)n;
	if (len >= sizeof(msg)) {
		len = sizeof(msg) - 1;
		memcpy(msg + len - (sizeof(truncated) - 1), truncated,
		       sizeof(truncated) - 1);
	}
	(void)write_retry(STDOUT_FILENO, msg, len);
	if (kmsg_fd < 0)
		goto done;

	memcpy(out, "<6>", 3);
	memcpy(out + 3, msg, len);
	written = write_retry(kmsg_fd, out, len + 3);
	if (written < 0) {
		int error = errno;

		fprintf(stderr, "mini-init: /dev/kmsg write failed: %s\n",
			strerror(error));
	} else if ((size_t)written != len + 3) {
		fprintf(stderr, "mini-init: short /dev/kmsg write: %zd/%zu\n",
			written, len + 3);
	}
done:
	errno = saved_errno;
}

static int make_dir(const char *path)
{
	struct stat st;

	if (mkdir(path, 0755) == 0)
		return 0;
	if (errno != EEXIST)
		return -1;
	if (stat(path, &st) < 0)
		return -1;
	if (!S_ISDIR(st.st_mode)) {
		errno = ENOTDIR;
		return -1;
	}
	return 0;
}

static int make_node(const char *path, mode_t mode,
		     unsigned int major_no, unsigned int minor_no)
{
	struct stat st;
	dev_t device = makedev(major_no, minor_no);

	if (mknod(path, mode, device) == 0)
		return 0;
	if (errno != EEXIST)
		return -1;
	if (stat(path, &st) < 0)
		return -1;
	if (!S_ISCHR(st.st_mode) || st.st_rdev != device) {
		errno = EINVAL;
		return -1;
	}
	return 0;
}

static void mount_fs(const char *name, const char *target)
{
	if (make_dir(target) < 0) {
		log_msg("mkdir %s: %s\n", target, strerror(errno));
		return;
	}
	if (mount(name, target, name, 0, NULL) < 0)
		log_msg("mount %s on %s: %s\n", name, target, strerror(errno));
}

static void dump_file(const char *path, const char *label)
{
	int fd;
	char buf[384];
	ssize_t n;
	int any = 0;

	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0) {
		log_msg("%s: <open failed: %s>\n", label, strerror(errno));
		return;
	}
	for (;;) {
		do {
			n = read(fd, buf, sizeof(buf) - 1);
		} while (n < 0 && errno == EINTR);
		if (n <= 0)
			break;

		/* Device-tree string lists contain NUL separators. */
		for (ssize_t i = 0; i < n; i++)
			if (buf[i] == '\0')
				buf[i] = ' ';
		buf[n] = '\0';
		log_msg("%s: %s\n", label, buf);
		any = 1;
	}
	if (n < 0)
		log_msg("%s: <read failed: %s>\n", label, strerror(errno));
	else if (!any)
		log_msg("%s: <empty>\n", label);
	close(fd);
}

static void list_dir(const char *path, const char *label)
{
	DIR *dir;
	struct dirent *de;
	int count = 0;
	int error;

	dir = opendir(path);
	if (!dir) {
		log_msg("%s: <opendir failed: %s>\n", label, strerror(errno));
		return;
	}
	for (;;) {
		errno = 0;
		de = readdir(dir);
		if (!de)
			break;
		if (de->d_name[0] == '.')
			continue;
		if (count < 24)
			log_msg("%s: %s\n", label, de->d_name);
		count++;
	}
	error = errno;
	closedir(dir);
	if (error)
		log_msg("%s: <readdir failed: %s>\n", label, strerror(error));
	log_msg("%s: %d entries%s\n", label, count,
		count > 24 ? " (only first 24 listed)" : "");
}

int main(void)
{
	int dev_dir_error = 0, dev_mount_error = 0;
	int console_node_error = 0, kmsg_node_error = 0, null_node_error = 0;
	int console_error = 0, console_fd, kmsg_error = 0;
	unsigned int remaining = 8;

	if (getpid() != 1) {
		fprintf(stderr, "mini-init must run as PID 1 in its initramfs\n");
		return EXIT_FAILURE;
	}

	if (make_dir("/dev") < 0)
		dev_dir_error = errno;
	if (mount("devtmpfs", "/dev", "devtmpfs", 0, NULL) < 0)
		dev_mount_error = errno;
	if (make_node("/dev/console", S_IFCHR | 0600, 5, 1) < 0)
		console_node_error = errno;
	if (make_node("/dev/kmsg", S_IFCHR | 0600, 1, 11) < 0)
		kmsg_node_error = errno;
	if (make_node("/dev/null", S_IFCHR | 0666, 1, 3) < 0)
		null_node_error = errno;

	console_fd = open("/dev/console", O_RDWR | O_CLOEXEC);
	if (console_fd >= 0) {
		for (int fd = 0; fd <= 2; fd++)
			if (dup2(console_fd, fd) < 0 && !console_error)
				console_error = errno;
		if (console_fd > 2)
			close(console_fd);
	} else {
		console_error = errno;
	}

	kmsg_fd = open("/dev/kmsg", O_WRONLY | O_CLOEXEC);
	if (kmsg_fd >= 0 && kmsg_fd <= 2) {
		int fd = fcntl(kmsg_fd, F_DUPFD_CLOEXEC, 3);
		int error = errno;

		close(kmsg_fd);
		kmsg_fd = fd;
		errno = error;
	}
	if (kmsg_fd < 0)
		kmsg_error = errno;

	log_msg("EVERT-4.19-MINI-INIT start: build=%s\n", MINI_INIT_BUILD_ID);
	if (dev_dir_error)
		log_msg("mkdir /dev: %s\n", strerror(dev_dir_error));
	if (dev_mount_error)
		log_msg("devtmpfs mount: %s (using static nodes)\n",
			strerror(dev_mount_error));
	if (console_node_error)
		log_msg("mknod /dev/console: %s\n", strerror(console_node_error));
	if (kmsg_node_error)
		log_msg("mknod /dev/kmsg: %s\n", strerror(kmsg_node_error));
	if (null_node_error)
		log_msg("mknod /dev/null: %s\n", strerror(null_node_error));
	if (console_error)
		log_msg("open/bind /dev/console: %s\n", strerror(console_error));
	if (kmsg_error)
		log_msg("open /dev/kmsg: %s; persistent marker unavailable\n",
			strerror(kmsg_error));

	mount_fs("proc", "/proc");
	mount_fs("sysfs", "/sys");
	dump_file("/proc/sys/kernel/random/boot_id", "boot_id");
	dump_file("/proc/version", "version");
	dump_file("/proc/cmdline", "cmdline");
	dump_file("/proc/device-tree/model", "model");
	dump_file("/proc/device-tree/compatible", "compatible");
	list_dir("/sys/class/block", "block");
	list_dir("/sys/class/regulator", "regulator");
	list_dir("/sys/bus/platform/devices", "platform");

	log_msg("EVERT-4.19-MINI-INIT OK: kernel reached userspace; build=%s\n",
		MINI_INIT_BUILD_ID);
	log_msg("rebooting in 8 seconds; collect pstore after reference boot\n");
	while (remaining)
		remaining = sleep(remaining);
	sync();

	if (reboot(RB_AUTOBOOT) < 0)
		log_msg("reboot failed: %s; keeping PID 1 alive\n", strerror(errno));
	else
		log_msg("reboot unexpectedly returned; keeping PID 1 alive\n");

	for (;;)
		pause();
}