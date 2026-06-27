"""Audio embedding generation using Essentia MusiCNN."""

from pathlib import Path

import numpy as np

from musicseed.logging_config import get_logger

logger = get_logger("embeddings.essentia")

# Embedding dimension for MusiCNN
EMBEDDING_DIM = 512


class EssentiaEmbedder:
    """Generate audio embeddings using Essentia's MusiCNN model."""

    def __init__(self):
        self._model = None
        self._extractor = None

    def _ensure_loaded(self) -> None:
        """Lazy load the Essentia model."""
        if self._extractor is not None:
            return

        try:
            from essentia.standard import TensorflowPredictMusiCNN

            logger.info("Loading Essentia embedding model...")

            # Use Discogs-EffNet which provides good music embeddings
            # This model outputs 1280-dim embeddings, we'll use PCA or average pooling
            # Actually, let's use MusiCNN which is more common

            # Use TensorflowPredictMusiCNN for 512-dim embeddings
            self._extractor = TensorflowPredictMusiCNN(
                graphFilename="",  # Use default model
                output="model/dense/BiasAdd",  # 512-dim embedding layer
            )

            logger.info("Essentia model loaded successfully")

        except ImportError as e:
            logger.error(f"Essentia not installed: {e}")
            raise RuntimeError(
                "Essentia is required for audio embeddings. "
                "Install with: pip install essentia-tensorflow"
            ) from e
        except Exception as e:
            logger.error(f"Failed to load Essentia model: {e}")
            raise

    def embed_file(self, file_path: str | Path) -> np.ndarray | None:
        """Generate embedding for an audio file.

        Args:
            file_path: Path to audio file (FLAC, MP3, WAV, etc.)

        Returns:
            512-dimensional numpy array, or None if failed
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
            embeddings = self._extractor(audio)

            # Average across time to get single embedding
            if len(embeddings.shape) > 1:
                embedding = np.mean(embeddings, axis=0)
            else:
                embedding = embeddings

            # Ensure correct dimension
            if embedding.shape[0] != EMBEDDING_DIM:
                logger.warning(
                    f"Unexpected embedding dimension: {embedding.shape[0]}, "
                    f"expected {EMBEDDING_DIM}"
                )
                # Pad or truncate if needed
                if embedding.shape[0] < EMBEDDING_DIM:
                    embedding = np.pad(embedding, (0, EMBEDDING_DIM - embedding.shape[0]))
                else:
                    embedding = embedding[:EMBEDDING_DIM]

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

            # Pad or truncate to 512 dimensions
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


def get_embedder(model: str = "essentia") -> EssentiaEmbedder | SimpleAudioEmbedder:
    """Get an audio embedder instance.

    Args:
        model: Model type ("essentia" or "simple")

    Returns:
        Embedder instance
    """
    if model == "essentia":
        try:
            embedder = EssentiaEmbedder()
            # Test that it can load
            embedder._ensure_loaded()
            return embedder
        except Exception as e:
            logger.warning(f"Essentia not available: {e}")
            logger.warning("Falling back to simple embedder")
            return SimpleAudioEmbedder()
    elif model == "simple":
        return SimpleAudioEmbedder()
    else:
        raise ValueError(f"Unknown embedding model: {model}")
