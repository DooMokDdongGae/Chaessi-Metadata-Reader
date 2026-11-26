"""Official publisher public anchors. Signing private keys are never included."""

CHANNEL = "public"
REALM = "public-production"
# Official public Ed25519 root; release keys rotate under this root-signed key set.
ROOTS = {
    "9072ff36eb99b5aa96be192a57c1366745b2bdbe90f0ca03f3a6a2617bc78c3a":
        bytes.fromhex("d24f437d721070229b8e378cedf14ede0685e3affd55d6cc43b219c495466c65"),
}
