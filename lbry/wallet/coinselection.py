from random import Random
from typing import List

from lbry.wallet.transaction import OutputEffectiveAmountEstimator

MAXIMUM_TRIES = 100000

STRATEGIES = ['sqlite']  # sqlite coin chooser is in database.py


def strategy(method):
    STRATEGIES.append(method.__name__)
    return method


class CoinSelector:

    def __init__(self, target: int, cost_of_change: int, seed: str = None) -> None:
        self.target = target
        self.cost_of_change = cost_of_change
        self.exact_match = False
        self.tries = 0
        self.random = Random(seed)
        if seed is not None:
            self.random.seed(seed, version=1)

    def select(
            self, txos: List[OutputEffectiveAmountEstimator],
            strategy_name: str = None) -> List[OutputEffectiveAmountEstimator]:
        if not txos:
            return []
        available = sum(c.effective_amount for c in txos)
        if self.target > available:
            return []
        return getattr(self, strategy_name or "standard")(txos, available)

    @strategy
    def prefer_confirmed(self, txos: List[OutputEffectiveAmountEstimator],
                         available: int) -> List[OutputEffectiveAmountEstimator]:
        return (
            self.only_confirmed(txos, available) or
            self.standard(txos, available)
        )

    @strategy
    def only_confirmed(self, txos: List[OutputEffectiveAmountEstimator],
                       _) -> List[OutputEffectiveAmountEstimator]:
        confirmed = [t for t in txos if t.txo.tx_ref and t.txo.tx_ref.height > 0]
        if not confirmed:
            return []
        confirmed_available = sum(c.effective_amount for c in confirmed)
        if self.target > confirmed_available:
            return []
        return self.standard(confirmed, confirmed_available)

    @strategy
    def standard(self, txos: List[OutputEffectiveAmountEstimator],
                 available: int) -> List[OutputEffectiveAmountEstimator]:
        return (
            self.branch_and_bound(txos, available) or
            self.closest_match(txos, available) or
            self.random_draw(txos, available)
        )

    @strategy
    def branch_and_bound(self, txos: List[OutputEffectiveAmountEstimator],
                         available: int) -> List[OutputEffectiveAmountEstimator]:
        # see bitcoin implementation for more info:
        # https://github.com/bitcoin/bitcoin/blob/master/src/wallet/coinselection.cpp

        txos.sort(reverse=True)

        current_value = 0
        current_available_value = available
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
                    current_available_value += txos[len(current_selection)].effective_amount

                if not current_selection:
                    break

                current_selection[-1] = False
                utxo = txos[len(current_selection) - 1]
                current_value -= utxo.effective_amount

            else:
                utxo = txos[len(current_selection)]
                current_available_value -= utxo.effective_amount
                previous_utxo = txos[len(current_selection) - 1] if current_selection else None
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
                txos[i] for i, include in enumerate(best_selection) if include
            ]

        return []

    @strategy
    def closest_match(self, txos: List[OutputEffectiveAmountEstimator],
                      _) -> List[OutputEffectiveAmountEstimator]:
        """ Pick one UTXOs that is larger than the target but with the smallest change. """
        target = self.target + self.cost_of_change
        smallest_change = None
        best_match = None
        for txo in txos:
            if txo.effective_amount >= target:
                change = txo.effective_amount - target
                if smallest_change is None or change < smallest_change:
                    smallest_change, best_match = change, txo
        return [best_match] if best_match else []

    @strategy
    def random_draw(self, txos: List[OutputEffectiveAmountEstimator],
                    _) -> List[OutputEffectiveAmountEstimator]:
        """ Accumulate UTXOs at random until there is enough to cover the target. """
        target = self.target + self.cost_of_change
        self.random.shuffle(txos, random=self.random.random)  # pylint: disable=deprecated-argument
        selection = []
        amount = 0
        for coin in txos:
            selection.append(coin)
            amount += coin.effective_amount
            if amount >= target:
                return selection
        return []
