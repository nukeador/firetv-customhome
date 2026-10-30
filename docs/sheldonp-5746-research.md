# Fire TV Stick 3rd generation: PS7717.5746N research

Status: research only. The installer does not run GhostLock on this build.

The public full firmware packages for sheldonp builds 5741 and 5746 were examined offline. Their SHA-256 hashes are respectively `6d04501e8f85afdef401ee50ea9d1a0482caac87a8084f7644453081ea714b4e` and `62c408cb35e59ac0de30b2cd4b876ddb037a09e80d106e9ad2ee1eb0ba8412ad`. The boot images were extracted and each ARM zImage was decompressed. Both decompressed images are 16,621,568 bytes, with 164 byte differences in six regions; several reflect build metadata. The SHA-256 hashes of the decompressed images are `e7976319600064bd908df494b5cda40d58eccfbddf54cf43e2951223d4466518` and `3552e95c82fb16d73a201d35673829b115b833caa448953a3f305e6f579dece5`.

In a comparison using image base `0xc0008000`, the first 128 bytes at each in-image 5741 profile anchor for init_task, ashmem functions, ashmem file operations, and configfs read/write were identical. The SELinux address was outside the decompressed image and could not be compared by this method. This is evidence for further analysis, not proof of a valid profile, of the running device image, or of safe execution.

GhostLock upstream 4.4 revision `57ed5a41809bf0e3c1b06388e5cdff77c2e6b89d` selects the incremental build exactly and does not contain a 5746 profile. Its stock root path disables and clears OTA packages. Before considering any live attempt, validate the runtime image and all anchors, review adaptation and rollback, preserve user-selected update settings, and test on the target. Do not bypass profile checks based on this comparison alone.

Sources: [GhostLock 4.4](https://github.com/R0rt1z2/GhostLock/tree/4.4), [5741 firmware](https://ftvdb.com/firetv/firmware/com.amazon.sheldonp.android.os/961d8cbb32124bfc6d3c1e40b6363c4e-36408028548-fire-os-7-7-1-7-ps7717-5741-2026-09-22/), [5746 firmware](https://ftvdb.com/firetv/firmware/com.amazon.sheldonp.android.os/e66e96eb6189ff3c392dcd749f712b33-36408029828-fire-os-7-7-1-7-ps7717-5746-2026-10-28/).
