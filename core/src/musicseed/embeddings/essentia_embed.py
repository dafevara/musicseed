"""Audio embedding generation using Essentia MusiCNN."""

import os
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlretrieve

import numpy as np

from musicseed.config import get_config
from musicseed.logging_config import get_logger

logger = get_logger("embeddings.essentia")

# Embedding dimension for the official Essentia MusiCNN feature layer.
EMBEDDING_DIM = 200
MUSICNN_MODEL_URL = "https://essentia.upf.edu/models/feature-extractors/musicnn/msd-musicnn-1.pb"
MUSICNN_MODEL_FILENAME = "msd-musicnn-1.pb"


class EssentiaModelError(RuntimeError):
    """Raised when the Essentia TensorFlow model cannot be resolved."""


def _default_model_path() -> Path:
    """Return the default local cache path for the Essentia MusiCNN model."""
    return Path.home() / ".cache" / "musicseed" / "models" / MUSICNN_MODEL_FILENAME


@contextmanager
def _suppress_native_output():
    """Temporarily silence native Essentia/TensorFlow stdout and stderr noise."""
    stdout_fd = os.dup(1)
    stderr_fd = os.dup(2)
    try:
        with open(os.devnull, "w") as null:
            os.dup2(null.fileno(), 1)
            os.dup2(null.fileno(), 2)
            yield
    finally:
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        os.close(stdout_fd)
        os.close(stderr_fd)


def resolve_musicnn_model_path() -> Path:
    """Resolve and optionally download the TensorFlow graph used by MusiCNN."""
    config = get_config().embedding
    if config.model_path:
        model_path = Path(config.model_path).expanduser()
    else:
        model_path = _default_model_path()

    if model_path.exists():
        return model_path

    if not config.auto_download_model:
        raise EssentiaModelError(
            "Essentia MusiCNN model file is missing. Set embedding.model_path in "
            "config.yaml to a valid .pb file, or enable embedding.auto_download_model. "
            f"Default cache path: {model_path}"
        )

    try:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = model_path.with_suffix(model_path.suffix + ".tmp")
        logger.info(f"Downloading Essentia MusiCNN model to {model_path}")
        urlretrieve(MUSICNN_MODEL_URL, temp_path)
        temp_path.replace(model_path)
    except (OSError, URLError) as e:
        raise EssentiaModelError(
            "Could not download the Essentia MusiCNN model. Download it manually from "
            f"{MUSICNN_MODEL_URL} and set embedding.model_path to the downloaded file. "
            f"Target path was: {model_path}"
        ) from e

    return model_path


def validate_musicnn_model() -> Path:
    """Resolve and load the MusiCNN model once to catch configuration errors early."""
    model_path = resolve_musicnn_model_path()
    embedder = EssentiaEmbedder(model_path)
    embedder._ensure_loaded()
    return model_path


class EssentiaEmbedder:
    """Generate audio embeddings using Essentia's MusiCNN model."""

    def __init__(self, model_path: str | Path | None = None):
        self._model = None
        self._extractor = None
        self._model_path = Path(model_path).expanduser() if model_path else None

    def _ensure_loaded(self) -> None:
        """Lazy load the Essentia model."""
        if self._extractor is not None:
            return

        try:
            from essentia.standard import TensorflowPredictMusiCNN

            logger.info("Loading Essentia embedding model...")

            model_path = self._model_path or resolve_musicnn_model_path()
            if not model_path.exists():
                raise EssentiaModelError(f"Essentia model file does not exist: {model_path}")

            # The official msd-musicnn-1 graph exposes 200-dimensional features here.
            with _suppress_native_output():
                self._extractor = TensorflowPredictMusiCNN(
                    graphFilename=str(model_path),
                    output="model/dense/BiasAdd",
                )

            logger.info("Essentia model loaded successfully")

        except ImportError as e:
            logger.error(f"Essentia not installed: {e}")
            raise RuntimeError(
                "Essentia is required for audio embeddings. "
                "Install with: pip install essentia-tensorflow"
            ) from e
        except EssentiaModelError:
            raise
        except Exception as e:
            logger.error(f"Failed to load Essentia model: {e}")
            raise

    def embed_file(self, file_path: str | Path) -> np.ndarray | None:
        """Generate embedding for an audio file.

        Args:
            file_path: Path to audio file (FLAC, MP3, WAV, etc.)

        Returns:
            200-dimensional numpy array, or None if failed
        """
        self._ensure_loaded()

        file_path = Path(file_path)
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return None

        try:
            import essentia.standard as es

            # Load audio (Essentia handles various formats)
            # Resample to 16kHz mono as required by MusiCNN
            audio = es.MonoLoader(filename=str(file_path), sampleRate=16000)()

            if len(audio) == 0:
                logger.warning(f"Empty audio file: {file_path}")
                return None

            # Get embeddings - MusiCNN processes in frames
            with _suppress_native_output():
                embeddings = np.asarray(self._extractor(audio), dtype=np.float32)

            # Average across time to get single embedding
            if len(embeddings.shape) > 1:
                embedding = np.mean(embeddings, axis=0)
            else:
                embedding = embeddings

            if embedding.shape[0] != EMBEDDING_DIM:
                logger.warning(
                    f"Unexpected MusiCNN embedding dimension: {embedding.shape[0]}, "
                    f"expected {EMBEDDING_DIM}"
                )
                return None

            return embedding.astype(np.float32)

        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            return None


class SimpleAudioEmbedder:
    """Fallback embedder using basic audio features when Essentia is unavailable."""

    def __init__(self):
        logger.warning("Using simple audio embedder (Essentia not available)")

    def embed_file(self, file_path: str | Path) -> np.ndarray | None:
        """Generate a simple embedding based on audio statistics.

        This is a fallback when Essentia is not available.
        Uses librosa for basic spectral features.
        """
        try:
            import librosa
            import numpy as np

            file_path = Path(file_path)
            if not file_path.exists():
                return None

            # Load audio
            y, sr = librosa.load(str(file_path), sr=22050, duration=60)

            if len(y) == 0:
                return None

            # Extract various features
            features = []

            # MFCCs (40 coefficients)
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
            features.extend(np.mean(mfcc, axis=1))
            features.extend(np.std(mfcc, axis=1))

            # Chroma (12 bins)
            chroma = librosa.feature.chroma_stft(y=y, sr=sr)
            features.extend(np.mean(chroma, axis=1))
            features.extend(np.std(chroma, axis=1))

            # Spectral features
            spec_cent = librosa.feature.spectral_centroid(y=y, sr=sr)
            features.extend([np.mean(spec_cent), np.std(spec_cent)])

            spec_bw = librosa.feature.spectral_bandwidth(y=y, sr=sr)
            features.extend([np.mean(spec_bw), np.std(spec_bw)])

            spec_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)
            features.extend([np.mean(spec_rolloff), np.std(spec_rolloff)])

            # Zero crossing rate
            zcr = librosa.feature.zero_crossing_rate(y)
            features.extend([np.mean(zcr), np.std(zcr)])

            # RMS energy
            rms = librosa.feature.rms(y=y)
            features.extend([np.mean(rms), np.std(rms)])

            # Tempo
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            features.append(tempo)

            # Pad or truncate to the configured embedding dimension
            embedding = np.array(features, dtype=np.float32)
            if len(embedding) < EMBEDDING_DIM:
                embedding = np.pad(embedding, (0, EMBEDDING_DIM - len(embedding)))
            else:
                embedding = embedding[:EMBEDDING_DIM]

            # Normalize
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            return embedding

        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            return None


_EMBEDDERS: dict[str, EssentiaEmbedder | SimpleAudioEmbedder] = {}


def get_embedder(model: str = "essentia") -> EssentiaEmbedder | SimpleAudioEmbedder:
    """Get an audio embedder instance.

    Args:
        model: Model type ("essentia" or "simple")

    Returns:
        Embedder instance
    """
    if model in _EMBEDDERS:
        return _EMBEDDERS[model]

    if model == "essentia":
        try:
            embedder = EssentiaEmbedder()
            # Test that it can load
            embedder._ensure_loaded()
            _EMBEDDERS[model] = embedder
            return embedder
        except Exception as e:
            logger.warning(f"Essentia not available: {e}")
            logger.warning("Falling back to simple embedder")
            embedder = SimpleAudioEmbedder()
            _EMBEDDERS[model] = embedder
            return embedder
    elif model == "simple":
        embedder = SimpleAudioEmbedder()
        _EMBEDDERS[model] = embedder
        return embedder
    else:
        raise ValueError(f"Unknown embedding model: {model}")
