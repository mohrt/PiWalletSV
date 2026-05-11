"""PiWallet: air-gapped Bitcoin SV signing device.

This is the offline-side library. It handles BIP39 mnemonics, BIP32/44
derivation, encrypted multi-wallet storage, BEEF-based SPV verification of
inbound proposals, and signing. It MUST NOT make network calls.
"""

__version__ = "0.1.0a0"
__all__ = ["__version__"]
