# GhostLock reconstruction

The installer downloads the public `kara-PS7713-5443-v1` release from
`Delitants/GhostLock` at commit `5a9e2b08d0dca369df442c612a2693d3e7a771c6`.
The upstream file SHA-256 is
`a42185d743ee1d4c9c46c1e35f5fa0a40f5e9a7f81450308c3eab297677847d5`.

`home-only-source.patch` documents the C changes that remove OTA modifications,
change the helper paths and confirmation token, and keep the root transition
limited to Home. The safety probe and the minimum reclaim score remain intact.

`assets/kara-home-only.bsdiff` is a binary delta, not the executable. The
installer checks its hash, applies it to the verified upstream executable, and
requires the reconstructed file SHA-256 to be
`46804934a67e34f260ee324161ec26288bc95a464fe02cb8dde93feb50d2aec0`.
That is the home-only binary previously tested on a single exact firmware. A
source rebuild with a different compiler is not assumed to produce that hash.

The upstream repository does not include a license file at the referenced
commit. Check redistribution rights for derived patches before publication.
The installer itself is not a substitute for a review of the exploit.
