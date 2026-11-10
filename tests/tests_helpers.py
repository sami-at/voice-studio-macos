"""Shared synthetic audio for tests."""
import numpy as np


def natural_take():
    """Quiet consonants around a vowel that rises and falls like a spoken one."""
    rng = np.random.default_rng(7)
    quiet = rng.uniform(-.0005, .0005, 4800).astype('float32')
    vowel = (.2 * np.hanning(12000) * np.sin(np.arange(12000) * .1)).astype('float32')
    return np.r_[np.zeros(2400), quiet, vowel, quiet, np.zeros(2400)].astype('float32')
