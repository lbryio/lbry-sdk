from __future__ import print_function
from random import Random

MAXIMUM_TRIES = 100000


class CoinSelector:

    def __init__(self, coins, target, cost_of_change, seed=None, debug=False):
        self.coins = coins
        self.target = target
        self.cost_of_change = cost_of_change
        self.exact_match = False
        self.tries = 0
        self.available = sum(c.effective_amount for c in self.coins)
        self.debug = debug
        self.random = Random(seed)
        debug and print(target)
        debug and print([c.effective_amount for c in self.coins])

    def select(self):
        if self.target > self.available:
            return
        if not self.coins:
            return
        return self.branch_and_bound() or self.single_random_draw()

    def single_random_draw(self):
        self.random.shuffle(self.coins)
        selection = []
        amount = 0
        for coin in self.coins:
            selection.append(coin)
            amount += coin.effective_amount
            if amount >= self.target+self.cost_of_change:
                return selection

    def branch_and_bound(self):
        # see bitcoin implementation for more info:
        # https://github.com/bitcoin/bitcoin/blob/master/src/wallet/coinselection.cpp

        self.coins.sort(reverse=True)

        current_value = 0
        current_available_value = self.available
        current_selection = []
        best_waste = self.cost_of_change
        best_selection = []

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
                    current_available_value += self.coins[len(current_selection)].effective_amount

                if not current_selection:
                    break

                current_selection[-1] = False
                utxo = self.coins[len(current_selection)-1]
                current_value -= utxo.effective_amount

            else:
                utxo = self.coins[len(current_selection)]
                current_available_value -= utxo.effective_amount
                previous_utxo = self.coins[len(current_selection)-1] if current_selection else None
                if current_selection and not current_selection[-1] and \
                   utxo.effective_amount == previous_utxo.effective_amount and \
                   utxo.fee == previous_utxo.fee:
                    current_selection.append(False)
                else:
                    current_selection.append(True)
                    current_value += utxo.effective_amount
                self.debug and print(current_selection)

        if best_selection:
            self.exact_match = True
            return [
                self.coins[i] for i, include in enumerate(best_selection) if include
            ]
