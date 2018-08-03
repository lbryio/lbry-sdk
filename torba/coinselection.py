from random import Random
from typing import List

from torba import basetransaction

MAXIMUM_TRIES = 100000


class CoinSelector:

    def __init__(self, txos: List[basetransaction.BaseOutputEffectiveAmountEstimator],
                 target: int, cost_of_change: int, seed: str = None) -> None:
        self.txos = txos
        self.target = target
        self.cost_of_change = cost_of_change
        self.exact_match = False
        self.tries = 0
        self.available = sum(c.effective_amount for c in self.txos)
        self.random = Random(seed)
        if seed is not None:
            self.random.seed(seed, version=1)

    def select(self) -> List[basetransaction.BaseOutputEffectiveAmountEstimator]:
        if not self.txos:
            return []
        if self.target > self.available:
            return []
        return (
            self.branch_and_bound() or
            self.closest_match() or
            self.random_draw()
        )

    def branch_and_bound(self) -> List[basetransaction.BaseOutputEffectiveAmountEstimator]:
        # see bitcoin implementation for more info:
        # https://github.com/bitcoin/bitcoin/blob/master/src/wallet/coinselection.cpp

        self.txos.sort(reverse=True)

        current_value = 0
        current_available_value = self.available
        current_selection: List[bool] = []
        best_waste = self.cost_of_change
        best_selection: List[bool] = []

        while self.tries < MAXIMUM_TRIES:
            self.tries += 1

            backtrack = False
            if current_value + current_available_value < self.target or \
               current_value > self.target + self.cost_of_change:
                backtrack = True
            elif current_value >= self.target:
                new_waste = current_value - self.target
                if new_waste <= best_waste:
                    best_waste = new_waste
                    best_selection = current_selection[:]
                backtrack = True

            if backtrack:
                while current_selection and not current_selection[-1]:
                    current_selection.pop()
                    current_available_value += self.txos[len(current_selection)].effective_amount

                if not current_selection:
                    break

                current_selection[-1] = False
                utxo = self.txos[len(current_selection) - 1]
                current_value -= utxo.effective_amount

            else:
                utxo = self.txos[len(current_selection)]
                current_available_value -= utxo.effective_amount
                previous_utxo = self.txos[len(current_selection) - 1] if current_selection else None
                if current_selection and not current_selection[-1] and previous_utxo and \
                   utxo.effective_amount == previous_utxo.effective_amount and \
                   utxo.fee == previous_utxo.fee:
                    current_selection.append(False)
                else:
                    current_selection.append(True)
                    current_value += utxo.effective_amount

        if best_selection:
            self.exact_match = True
            return [
                self.txos[i] for i, include in enumerate(best_selection) if include
            ]

        return []

    def closest_match(self) -> List[basetransaction.BaseOutputEffectiveAmountEstimator]:
        """ Pick one UTXOs that is larger than the target but with the smallest change. """
        target = self.target + self.cost_of_change
        smallest_change = None
        best_match = None
        for txo in self.txos:
            if txo.effective_amount >= target:
                change = txo.effective_amount - target
                if smallest_change is None or change < smallest_change:
                    smallest_change, best_match = change, txo
        return [best_match] if best_match else []

    def random_draw(self) -> List[basetransaction.BaseOutputEffectiveAmountEstimator]:
        """ Accumulate UTXOs at random until there is enough to cover the target. """
        target = self.target + self.cost_of_change
        self.random.shuffle(self.txos, self.random.random)
        selection = []
        amount = 0
        for coin in self.txos:
            selection.append(coin)
            amount += coin.effective_amount
            if amount >= target:
                return selection
        return []
