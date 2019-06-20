#coding:utf-8
"""
This module contains the core voting system logic.
"""
from tabulate import tabulate

from table_util import entropy, add_totals
from excel_util import election_to_xlsx
from apportion import apportion1d, threshold_elimination_totals, \
    threshold_elimination_constituencies
from electionRules import ElectionRules
from dictionaries import ADJUSTMENT_METHODS

class Election:
    """A single election."""
    def __init__(self, rules, votes=None, name=''):
        self.num_constituencies = len(rules["constituencies"])
        self.rules = rules
        self.name = name
        self.set_votes(votes)

    def entropy(self):
        return entropy(self.m_votes, self.results, self.gen)

    def set_votes(self, votes):
        assert(len(votes) == self.num_constituencies)
        assert(all([len(x) == len(self.rules["parties"])
                    for x in votes]))
        self.m_votes = votes
        self.v_votes = [sum(x) for x in zip(*votes)]

    def get_results_dict(self):
        return {
            "rules": self.rules,
            "seat_allocations": add_totals(self.results),
        }

    def run(self):
        """Run an election based on current rules and votes."""
        # How many constituency seats does each party get in each constituency:
        self.const_seats_alloc = []
        # Which seats does each party get in each constituency:
        self.order = []
        # Determine total seats (const + adjustment) in each constituency:
        self.v_total_seats = [
            const["num_const_seats"] + const["num_adj_seats"]
            for const in self.rules["constituencies"]
        ]
        # Determine total seats in play:
        self.total_seats = sum(self.v_total_seats)

        self.run_primary_apportionment()
        self.run_threshold_elimination()
        self.run_determine_adjustment_seats()
        self.run_adjustment_apportionment()
        return self.results

    def run_primary_apportionment(self):
        """Conduct primary apportionment"""
        if self.rules["debug"]:
            print(" + Primary apportionment")

        gen = self.rules.get_generator("primary_divider")
        constituencies = self.rules["constituencies"]
        parties = self.rules["parties"]

        m_allocations = []
        self.last = []
        for i in range(len(constituencies)):
            num_seats = constituencies[i]["num_const_seats"]
            if num_seats != 0:
                alloc, div = apportion1d(self.m_votes[i], num_seats, [0]*len(parties), gen)
                self.last.append(div[2])
            else:
                alloc = [0]*len(parties)
                self.last.append(0)
            m_allocations.append(alloc)
            # self.order.append(seats)

        # Useful:
        # print tabulate([[parties[x] for x in y] for y in self.order])

        v_allocations = [sum(x) for x in zip(*m_allocations)]

        self.m_const_seats_alloc = m_allocations
        self.v_const_seats_alloc = v_allocations

    def run_threshold_elimination(self):
        """Eliminate parties that do not reach the adjustment threshold."""
        if self.rules["debug"]:
            print(" + Threshold elimination")
        threshold = self.rules["adjustment_threshold"]*0.01
        v_elim_votes = threshold_elimination_totals(self.m_votes, threshold)
        m_elim_votes = threshold_elimination_constituencies(self.m_votes,
                                                            threshold)
        self.v_votes_eliminated = v_elim_votes
        self.m_votes_eliminated = m_elim_votes

    def run_determine_adjustment_seats(self):
        """Calculate the number of adjustment seats each party gets."""
        if self.rules["debug"]:
            print(" + Determine adjustment seats")
        v_votes = self.v_votes_eliminated
        gen = self.rules.get_generator("adj_determine_divider")
        v_priors = self.v_const_seats_alloc
        v_seats, _ = apportion1d(v_votes, self.total_seats, v_priors, gen)
        self.v_adjustment_seats = v_seats
        return v_seats

    def run_adjustment_apportionment(self):
        """Conduct adjustment seat apportionment."""
        if self.rules["debug"]:
            print(" + Apportion adjustment seats")
        method = ADJUSTMENT_METHODS[self.rules["adjustment_method"]]
        gen = self.rules.get_generator("adj_alloc_divider")

        results, asi = method(self.m_votes_eliminated,
            self.v_total_seats,
            self.v_adjustment_seats,
            self.m_const_seats_alloc,
            gen,
            self.rules["adjustment_threshold"]*0.01,
            orig_votes=self.m_votes,
            last=self.last)

        self.adj_seats_info = asi

        self.results = results
        self.gen = gen

        v_results = [sum(x) for x in zip(*results)]
        devs = [abs(a-b) for a, b in zip(self.v_adjustment_seats, v_results)]
        self.adj_dev = sum(devs)

        if self.rules["show_entropy"]:
            print("\nEntropy: %s" % self.entropy())

    def to_xlsx(self, filename):
        election_to_xlsx(self, filename)


def run_script_election(rules):
    rs = ElectionRules()
    if "election_rules" not in rules:
        return {"error": "No election rules supplied."}

    rs.update(rules["election_rules"])

    if not "votes" in rs:
        return {"error": "No votes supplied"}

    election = Election(rs, rs["votes"])
    election.run()

    return election

if __name__ == "__main__":
    pass
