"""AES decryption helpers for encrypted TIDAL streams."""

import base64
import pathlib

from Crypto.Cipher import AES
from Crypto.Util import Counter


def decrypt_security_token(security_token: str) -> tuple[bytes, bytes]:
    """Decrypt a TIDAL security token into an AES key and nonce.

    Args:
        security_token (str): Base64-encoded security token from the stream manifest.

    Returns:
        tuple[bytes, bytes]: (key, nonce) for AES-CTR decryption.
    """
    master_key = "UIlTTEMmmLfGowo/UC60x2H45W6MdGgTRfo/umg4754="
    master_key = base64.b64decode(master_key)
    security_token = base64.b64decode(security_token)

    iv = security_token[:16]
    encrypted_st = security_token[16:]

    decryptor = AES.new(master_key, AES.MODE_CBC, iv)
    decrypted_st = decryptor.decrypt(encrypted_st)

    key = decrypted_st[:16]
    nonce = decrypted_st[16:24]

    return key, nonce


def decrypt_file(
    path_file_encrypted: pathlib.Path,
    path_file_destination: pathlib.Path,
    key: bytes,
    nonce: bytes,
) -> None:
    """Decrypt an AES-CTR encrypted media file.

    Args:
        path_file_encrypted (pathlib.Path): Source encrypted file.
        path_file_destination (pathlib.Path): Destination for the decrypted output.
        key (bytes): AES decryption key.
        nonce (bytes): AES-CTR nonce.
    """
    counter = Counter.new(64, prefix=nonce, initial_value=0)
    decryptor = AES.new(key, AES.MODE_CTR, counter=counter)

    with path_file_encrypted.open("rb") as f_src:
        audio_decrypted = decryptor.decrypt(f_src.read())

        with path_file_destination.open("wb") as f_dst:
            f_dst.write(audio_decrypted)
