#coding:utf-8
"""
This module contains the core voting system logic.
"""
import random
import json
from copy import copy
from tabulate import tabulate
from util import load_votes, load_constituencies, entropy
from apportion import apportion1d
from rules import Rules
from simulate import SimulationRules # TODO: This belongs elsewhere.
from methods import *
import io

def dhondt_gen():
    """Generate a d'Hondt divider sequence: 1, 2, 3..."""
    n = 1
    while True:
        yield n
        n += 1

def sainte_lague_gen():
    """Generate a Sainte-Lague divider sequence: 1, 3, 5..."""
    n = 1
    while True:
        yield n
        n += 2

def swedish_sainte_lague_gen():
    """Generate a Swedish/Nordic Sainte-Lague divide sequence: 1.4, 3, 5..."""
    yield 1.4
    n = 3
    while True:
        yield n
        n += 2

DIVIDER_RULES = {
    "dhondt": dhondt_gen,
    "sainte-lague": sainte_lague_gen,
    "swedish": swedish_sainte_lague_gen
}

DIVIDER_RULE_NAMES = {
    "dhondt": "D'Hondt's method",
    "sainte-lague": "Sainte-Laguë method",
    "swedish": "Nordic Sainte-Laguë variant"
}


class ElectionRules(Rules):
    """A set of rules for an election or a simulation to follow."""

    def __init__(self):
        super(ElectionRules, self).__init__()
        self.value_rules = {
            "primary_divider": DIVIDER_RULES.keys(),
            "adjustment_divider": DIVIDER_RULES.keys(),
            "adjustment_method": ADJUSTMENT_METHODS.keys(),
            "simulation_variate": SIMULATION_VARIATES.keys(),
        }
        self.range_rules = {
            "adjustment_threshold": [0.0, 1.0]
        }
        self.list_rules = [
            "constituency_seats", "constituency_adjustment_seats",
            "constituency_names", "parties"
        ]

        # Election rules
        self["primary_divider"] = "dhondt"
        self["adjustment_divider"] = "dhondt"
        self["adjustment_threshold"] = 0.05
        self["adjustment_method"] = "icelandic-law"
        self["constituency_seats"] = []
        self["constituency_adjustment_seats"] = []
        self["constituency_names"] = []
        self["parties"] = []

        # Display rules
        self["debug"] = False
        self["show_entropy"] = False
        self["output"] = "simple"

    def __setitem__(self, key, value):
        if key == "constituencies":
            value = load_constituencies(value)
            self["constituency_names"] = [x["name"] for x in value]
            self["constituency_seats"] = [x["num_constituency_seats"]
                                          for x in value]
            self["constituency_adjustment_seats"] = [x["num_adjustment_seats"]
                                                     for x in value]

        super(ElectionRules, self).__setitem__(key, value)

    def get_generator(self, div):
        """Fetch a generator from divider rules."""
        method = self[div]
        if method in DIVIDER_RULES.keys():
            return DIVIDER_RULES[method]
        else:
            raise ValueError("%s is not a known divider" % div)


class Election:
    """A single election."""
    def __init__(self, rules, votes=None):
        self.m_votes = votes
        self.rules = rules
        self.order = []
        self.log = []

    def set_votes(self, votes):
        assert(len(votes) == len(self.rules["constituencies"]))
        assert(all([len(votes[x]) == len(self.rules["parties"])
                    for x in votes]))
        self.m_votes = votes

    def load_votes(self, votesfile):
        parties, votes = load_votes(votesfile)
        self.rules["parties"] = parties
        assert(len(votes) == len(self.rules["constituencies"]))
        assert(all([len(votes[x]) == len(self.rules["parties"])
                    for x in votes]))
        self.m_votes = votes
        self.v_parties = parties

    def get_results_dict(self):
        return {
            "rules": self.rules,
            "seat_allocations": self.results,
        }

    def run(self):
        """Run an election based on current rules and votes."""
        # How many seats does each party get in each constituency:
        self.m_allocations = []
        # Which seats does each party get in each constituency:
        self.m_seats = []
        # Determine total seats (const + adjustment) in each constituency:
        self.v_total_seats = [sum(x) for x in
                              zip(self.rules["constituency_seats"],
                                  self.rules["constituency_adjustment_seats"])
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
        m_allocations, v_seatcount = self.primary_apportionment(self.m_votes)
        self.m_allocations = m_allocations
        self.v_cur_allocations = v_seatcount

    def run_threshold_elimination(self):
        if self.rules["debug"]:
            print(" + Threshold elimination")
        threshold = self.rules["adjustment_threshold"]
        v_elim_votes = threshold_elimination_totals(self.m_votes, threshold)
        m_elim_votes = threshold_elimination_constituencies(self.m_votes,
                                                            threshold)
        self.v_votes_eliminated = v_elim_votes
        self.m_votes_eliminated = m_elim_votes

    def run_determine_adjustment_seats(self):
        """
        Calculate the number of adjusment seats each party gets.
        """
        if self.rules["debug"]:
            print(" + Determine adjustment seats")
        v_votes = self.v_votes_eliminated
        gen = self.rules.get_generator("adjustment_divider")
        v_priors = self.v_cur_allocations
        v_seats, divs = apportion1d(v_votes, self.total_seats, v_priors, gen)
        self.v_adjustment_seats = v_seats
        return v_seats

    def run_adjustment_apportionment(self):
        if self.rules["debug"]:
            print(" + Apportion adjustment seats")
        method = ADJUSTMENT_METHODS[self.rules["adjustment_method"]]
        gen = self.rules.get_generator("adjustment_divider")

        results = method(self.m_votes_eliminated,
                         self.v_total_seats,
                         self.v_adjustment_seats,
                         self.m_allocations,
                         gen,
                         self.rules["adjustment_threshold"],
                         orig_votes=self.m_votes)

        self.results = results

        # header = ["Constituency"]
        # header.extend(self.rules["parties"])
        # print "\n=== %s ===" %
        #    (ADJUSTMENT_METHOD_NAMES[self.rules["adjustment_method"]])
        # data = [[self.rules["constituency_names"][c]]+results[c] for c in
        #         range(len(self.rules["constituency_names"]))]
        # print tabulate(data, header, "simple")

        if self.rules["show_entropy"]:
            ent = entropy(self.m_votes, results, gen)
            print("\nEntropy: ", ent)

    def primary_apportionment(self, m_votes):
        """Do primary allocation of seats for all constituencies"""
        gen = self.rules.get_generator("primary_divider")
        const = self.rules["constituency_seats"]
        parties = self.rules["parties"]

        m_allocations = []
        for i in range(len(const)):
            num_seats = const[i]
            rounds, seats = constituency_seat_allocation(m_votes[i], num_seats,
                                                         gen)
            v_allocations = [seats.count(p) for p in range(len(parties))]
            m_allocations.append(v_allocations)
            self.order.append(seats)

        # Useful:
        # print tabulate([[parties[x] for x in y] for y in self.order])

        v_seatcount = [sum([x[i] for x in m_allocations]) for i in range(len(parties))]

        return m_allocations, v_seatcount


def primary_seat_allocation(m_votes, const, parties, gen):
    """Do primary allocation of seats for all constituencies"""
    m_allocations = []
    for i in range(len(const)):
        s = const[i]["num_constituency_seats"]
        rounds, seats = constituency_seat_allocation(m_votes[i], s, gen)
        named_seats = [parties[x] for x in seats]
        v_allocations = [seats.count(p) for p in range(len(parties))]
        # print "%-20s: %s" % (const[i]["name"], ", ".join(named_seats))
        m_allocations.append(v_allocations)

    v_seatcount = [sum([x[i] for x in m_allocations]) for i in range(len(parties))]

    return m_allocations, v_seatcount


def constituency_seat_allocation(v_votes, num_seats, gen):
    """Do primary seat allocation for one constituency"""
    # FIXME: This should use apportion1d() instead
    rounds = []
    seats = []
    alloc_votes = copy(v_votes)
    gens = [gen() for x in range(len(v_votes))]
    divisors = [next(x) for x in gens]

    for i in range(num_seats):
        maxval = max(alloc_votes)
        idx = alloc_votes.index(maxval)
        res = {
            "maxval": maxval,
            "votes": alloc_votes,
            "winner": idx,
            "divisor": divisors[idx]
        }
        seats.append(idx)
        rounds.append(res)
        divisors[idx] = next(gens[idx])
        alloc_votes[idx] = v_votes[idx] / divisors[idx]

    return rounds, seats


def threshold_elimination_constituencies(votes, threshold, party_seats=None, priors=None):
    """
    Eliminate parties that don't reach national threshold.
    Optionally, eliminate parties that have already gotten all their
    calculated seats.

    Inputs:
        - votes: Matrix of votes.
        - threshold: Real value between 0.0 and 1.0 with the cutoff threshold.
        - [party_seats]: seats that should be allocated to each party
        - [priors]: a matrix of prior allocations to each party per constituency
    Returns: Matrix of votes with eliminated parties zeroed out.
    """
    N = len(votes[0])
    totals = [sum([x[i] for x in votes]) for i in range(N)]
    country_total = sum(totals)
    percent = [float(t)/country_total for t in totals]
    m_votes = []

    for c in votes:
        cons = []
        for i in range(N):
            if percent[i] > threshold:
                v = c[i]
            else:
                v = 0
            cons.append(v)
        m_votes.append(cons)

    if not (priors and party_seats):
        return m_votes

    for j in range(N):
        if party_seats[j] == sum([m[j] for m in priors]):
            for i in range(len(votes)):
                m_votes[i][j] = 0

    return m_votes

def threshold_elimination_totals(votes, threshold):
    """
    Eliminate parties that do not reach the threshold proportion of
    national votes. Replaces such parties with zeroes.
    """
    N = len(votes[0])
    totals = [sum([x[i] for x in votes]) for i in range(N)]
    country_total = sum(totals)
    percent = [float(t)/country_total for t in totals]
    cutoff = [totals[i] if percent[i] > threshold else 0 for i in range(len(totals))]

    return cutoff



ADJUSTMENT_METHODS = {
    "alternating-scaling": alternating_scaling,
    "relative-superiority": relative_superiority,
    "relative-inferiority": relative_inferiority,
    "monge": monge,
    "icelandic-law": icelandic_apportionment,
}

ADJUSTMENT_METHOD_NAMES = {
    "alternating-scaling": "Alternating-Scaling Method",
    "relative-superiority": "Relative Superiority Method",
    "relative-inferiority": "Relative Inferiority Method",
    "monge": "Monge algorithm",
    "icelandic-law": "Icelandic law 24/2000 (Kosningar til Alþingis)"
}

class Variate:
    def __init__(self, election):
        self.election = election

    def step(index):
        pass


class VariateBeta(Variate):
    pass


class VariateBruteforce(Variate):
    pass


SIMULATION_VARIATES = {
    "beta": VariateBeta,
    "bruteforce": VariateBruteforce,
}

# TODO: These functions should be elsewhere.

def get_capabilities_dict():
    return {
        "election_rules": ElectionRules(),
        "simulation_rules": SimulationRules(),
        "capabilities": {
            "divider_rules": DIVIDER_RULE_NAMES,
            "adjustment_methods": ADJUSTMENT_METHOD_NAMES,
        },
        "presets": get_presets()
    }

def get_presets():
    from os import listdir
    from os.path import isfile, join
    presetsdir = "../data/presets/"
    try:
        files = [f for f in listdir(presetsdir) if isfile(join(presetsdir, f))]
    except Exception as e:
        print("Presets directory read failure: %s" % (e))
        files = []
    pr = []
    for f in files:
        try:
            with open(presetsdir+f) as json_file:    
                data = json.load(json_file)
                # pr.append(io.open(presetsdir+f).read())
        except  json.decoder.JSONDecodeError:
            data = {'error': 'Problem parsing json, please fix "{}"'.format(
                presetsdir+f)}
        pr.append(data)
    return pr

def run_script(rules):
    if type(rules) != dict:
        return {"error": "Incorrect script format."}

    if rules["action"] not in ["simulation", "election"]:
        return {"error": "Script action must be election or simulation."}

    if rules["action"] == "election":
        rs = ElectionRules()
        if "election_rules" not in rules:
            return {"error": "No election rules supplied."}

        rs.update(rules["election_rules"])

        if not "votes" in rs:
            return {"error": "No votes supplied"}

        election = Election(rs, rs["votes"])
        election.run()

        return election

    else:
        return {"error": "Not implemented."}


if __name__ == "__main__":
    pass