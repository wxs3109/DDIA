"""
Bloom Filter — probabilistic set membership.

Used by SSTable to skip disk reads for keys that definitely don't exist.
False positives are possible (may say "maybe" when key is absent).
False negatives are impossible (never says "no" when key exists).

Math:
  m = optimal bit array size  = -n * ln(p) / ln(2)^2
  k = optimal hash func count =  m/n * ln(2)
where n = expected capacity, p = desired false positive rate.
"""

import hashlib
import math


class BloomFilter:
    def __init__(self, capacity: int, false_positive_rate: float = 0.01):
        self.capacity = capacity
        self.fpr = false_positive_rate
        self.m = math.ceil(-(capacity * math.log(false_positive_rate)) / (math.log(2) ** 2))
        self.k = max(1, round((self.m / capacity) * math.log(2)))
        self.bits = bytearray(math.ceil(self.m / 8))
        self.count = 0

    def _bit_positions(self, key: str) -> list[int]:
        positions = []
        for i in range(self.k):
            seed = key.encode() + i.to_bytes(2, "big")
            h = int(hashlib.md5(seed).hexdigest(), 16)
            positions.append(h % self.m)
        return positions

    def add(self, key: str) -> None:
        for pos in self._bit_positions(key):
            self.bits[pos // 8] |= 1 << (pos % 8)
        self.count += 1

    def maybe_contains(self, key: str) -> bool:
        return all(
            self.bits[pos // 8] & (1 << (pos % 8))
            for pos in self._bit_positions(key)
        )

    def to_bytes(self) -> bytes:
        header = self.m.to_bytes(8, "big") + self.k.to_bytes(4, "big")
        return header + bytes(self.bits)

    @classmethod
    def from_bytes(cls, data: bytes) -> "BloomFilter":
        m = int.from_bytes(data[:8], "big")
        k = int.from_bytes(data[8:12], "big")
        bf = cls.__new__(cls)
        bf.m = m
        bf.k = k
        bf.bits = bytearray(data[12:])
        bf.count = 0
        bf.capacity = 0
        bf.fpr = 0.0
        return bf

    def __repr__(self) -> str:
        return (
            f"BloomFilter(m={self.m} bits, k={self.k} hashes, "
            f"count={self.count}, fpr~{self.fpr})"
        )
