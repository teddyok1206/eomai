"""Offline FP32 fine-generator inference in the existing protected numerical environment."""

from __future__ import annotations

import io
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import metadata
from typing import Any

from eom_image_contracts import InformativeLineartExtractionRuntime
from PIL import Image

from eom_image_provider.informative_lineart_extraction import ExtractedLineart
from eom_image_provider.informative_lineart_model import load_informative_lineart_safetensors
from eom_image_provider.informative_lineart_resolution import ResolvedInformativeLineartMaterial
from eom_image_provider.provider import ProviderError


class InformativeLineartTorchSession:
    def __init__(
        self, generator: Any, torch: Any, runtime: InformativeLineartExtractionRuntime
    ) -> None:
        self.generator = generator
        self.torch = torch
        self.runtime = runtime

    def extract(self, fitted_rgb_png: bytes) -> ExtractedLineart:
        import numpy as np

        with Image.open(io.BytesIO(fitted_rgb_png)) as source:
            if source.format != "PNG" or source.mode != "RGB" or source.size != (832, 512):
                raise ProviderError("LINEART_EXTRACTION_INPUT_INVALID")
            source.load()
            raster = np.asarray(source, dtype=np.float32) / 255
        try:
            tensor = (
                self.torch.from_numpy(raster)
                .permute(2, 0, 1)
                .unsqueeze(0)
                .to("cuda", dtype=self.torch.float32)
            )
            with self.torch.inference_mode():
                output = self.generator(tensor)
            self.torch.cuda.synchronize(0)
            if (
                output.shape != (1, 1, 512, 832)
                or output.dtype != self.torch.float32
                or not self.torch.isfinite(output).all().item()
                or output.min().item() < 0
                or output.max().item() > 1
            ):
                raise ProviderError("LINEART_EXTRACTION_OUTPUT_INVALID")
            pixels = output[0, 0].mul(255).round().to(self.torch.uint8).cpu().numpy()
            stream = io.BytesIO()
            Image.fromarray(pixels).save(stream, format="PNG", compress_level=9)
            return ExtractedLineart(stream.getvalue(), self.torch.cuda.max_memory_allocated(0))
        except ProviderError:
            raise
        except self.torch.cuda.OutOfMemoryError as exc:
            raise ProviderError("LINEART_EXTRACTION_OOM") from exc
        except Exception as exc:
            raise ProviderError("LINEART_EXTRACTION_EXEC_FAILED") from exc


class InformativeLineartTorchBackend:
    @contextmanager
    def open(
        self, material: ResolvedInformativeLineartMaterial
    ) -> Iterator[InformativeLineartTorchSession]:
        try:
            import torch  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderError("LINEART_EXTRACTION_MODEL_INVALID") from exc
        if not torch.cuda.is_available() or torch.cuda.get_device_capability(0) != (12, 0):
            raise ProviderError("LINEART_EXTRACTION_GPU_UNAVAILABLE")
        session = None
        generator = None
        try:
            runtime = InformativeLineartExtractionRuntime.model_validate(
                {
                    "provider_version": "eom-informative-lineart-extractor/1.0",
                    "torch_version": torch.__version__,
                    "safetensors_version": metadata.version("safetensors"),
                    "pillow_version": metadata.version("Pillow"),
                    "cuda_version": torch.version.cuda,
                    "compute_capability": "12.0",
                    "dtype": "float32",
                    "gpu_name": torch.cuda.get_device_name(0),
                }
            )
            torch.cuda.reset_peak_memory_stats(0)
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
            torch.use_deterministic_algorithms(True)
            generator = load_informative_lineart_safetensors(material.weight_bytes, torch=torch).to(
                "cuda", dtype=torch.float32
            )
            session = InformativeLineartTorchSession(generator, torch, runtime)
            yield session
        except ProviderError:
            raise
        except torch.cuda.OutOfMemoryError as exc:
            raise ProviderError("LINEART_EXTRACTION_OOM") from exc
        except Exception as exc:
            raise ProviderError("LINEART_EXTRACTION_MODEL_INVALID") from exc
        finally:
            if session is not None:
                session.generator = None
            generator = None
            torch.cuda.empty_cache()
