import json
import logging
import os
import re
import subprocess  # nosec
from connaisseur.validators.interface import ValidatorInterface
from connaisseur.image import Image
from connaisseur.exceptions import (
    CosignError,
    CosignTimeout,
    NotFoundException,
    ValidationError,
    UnexpectedCosignData,
    InvalidFormatException,
)
from connaisseur.crypto import load_key


class CosignValidator(ValidatorInterface):
    name: str
    trust_roots: list

    def __init__(self, name: str, trust_roots: list, **kwargs):
        super().__init__(name, **kwargs)
        self.trust_roots = trust_roots

    def __get_key(self, key_name: str = None):
        key_name = key_name or "default"
        try:
            key = next(
                key["key"] for key in self.trust_roots if key["name"] == key_name
            )
        except StopIteration as err:
            msg = 'Trust root "{key_name}" not configured for validator "{validator_name}".'
            raise NotFoundException(
                message=msg, key_name=key_name, validator_name=self.name
            ) from err
        return "".join(key)

    def validate(
        self, image: Image, trust_root: str = None, **kwargs
    ):  # pylint: disable=arguments-differ
        pub_key = self.__get_key(trust_root)
        return self.__get_cosign_validated_digests(str(image), pub_key).pop()

    def __get_cosign_validated_digests(self, image: str, pubkey: str):
        """
        Gets and processes Cosign validation output for a given `image` and `pubkey`
        and either returns a list of valid digests or raises a suitable exception
        in case no valid signature is found or Cosign fails.
        """
        returncode, stdout, stderr = self.__invoke_cosign(image, pubkey)
        logging.info(
            "COSIGN output for image: %s; RETURNCODE: %s; STDOUT: %s; STDERR: %s",
            image,
            returncode,
            stdout,
            stderr,
        )
        digests = []
        if returncode == 0:
            for sig in stdout.splitlines():
                try:
                    sig_data = json.loads(sig)
                    try:
                        digest = sig_data["critical"]["image"].get(
                            "docker-manifest-digest", ""
                        )
                        if re.match(r"sha256:[0-9A-Fa-f]{64}", digest) is None:
                            msg = "Digest '{digest}' does not match expected digest pattern."
                            raise InvalidFormatException(message=msg, digest=digest)
                    except Exception as err:
                        msg = (
                            "Could not retrieve valid and unambiguous digest from data "
                            "received by Cosign: {err_type}: {err}"
                        )
                        raise UnexpectedCosignData(
                            message=msg, err_type=type(err).__name__, err=str(err)
                        ) from err
                    # remove prefix 'sha256'
                    digests.append(digest.removeprefix("sha256:"))
                except json.JSONDecodeError:
                    logging.info("non-json signature data from Cosign: %s", sig)
                    pass
        elif "error: no matching signatures:\nfailed to verify signature\n" in stderr:
            msg = "Failed to verify signature of trust data."
            raise ValidationError(
                message=msg,
                trust_data_type="dev.cosignproject.cosign/signature",
                stderr=stderr,
            )
        elif re.match(
            r"^error: fetching signatures: getting signature manifest: "
            r"GET https://[^ ]+ MANIFEST_UNKNOWN:.*",
            stderr,
        ):
            msg = 'No trust data for image "{image}".'
            raise NotFoundException(
                message=msg,
                trust_data_type="dev.cosignproject.cosign/signature",
                stderr=stderr,
                image=str(image),
            )
        else:
            msg = 'Unexpected Cosign exception for image "{image}": {stderr}.'
            raise CosignError(
                message=msg,
                trust_data_type="dev.cosignproject.cosign/signature",
                stderr=stderr,
                image=str(image),
            )
        if not digests:
            msg = (
                "Could not extract any digest from data received by Cosign "
                "despite successful image verification."
            )
            raise UnexpectedCosignData(message=msg)
        return digests

    def __invoke_cosign(self, image, pubkey):
        """
        Invokes the Cosign binary in a subprocess for a specific `image` given a `pubkey` and
        returns the returncode, stdout and stderr. Will raise an exception if Cosign times out.
        """

        env = os.environ
        # Extend the OS env vars only for passing to the subprocess below
        env["DOCKER_CONFIG"] = f"/app/connaisseur-config/{self.name}/.docker/"

        try:
            key = load_key(pubkey).to_pem()  # raises if invalid
        except ValueError as err:
            if re.match(r"^\w{2,20}\:\/\/[\w:\/-]{3,255}$", pubkey) is None:
                msg = (
                    "Public key (or reference in case of KMS) '{key}' does not match "
                    "expected pattern."
                )
                raise InvalidFormatException(message=msg, key=pubkey) from err
            key = b""
        cmd = [
            "/app/cosign/cosign",
            "verify",
            "-output",
            "text",
            "-key",
            "/dev/stdin" if key else pubkey,
            image,
        ]

        with subprocess.Popen(  # nosec
            cmd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as process:
            try:
                stdout, stderr = process.communicate(key, timeout=60)
            except subprocess.TimeoutExpired as err:
                process.kill()
                msg = "Cosign timed out."
                raise CosignTimeout(
                    message=msg, trust_data_type="dev.cosignproject.cosign/signature"
                ) from err

        return process.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")

    @property
    def healthy(self):
        return True
