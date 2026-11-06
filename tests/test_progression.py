from flytbase_bdr.progression import choose_branch


def test_new_information_changes_next_branch_and_goal():
    interest = choose_branch("Interested. Can we arrange a discussion?")
    budget = choose_branch("Our budget meeting is in Q3, no funds approved yet.")
    referral = choose_branch("Please contact our procurement colleague.")
    no_reply = choose_branch("", no_reply=True)
    assert [d["branch"] for d in [interest, budget, referral, no_reply]] == ["interested", "budget_clarification", "stakeholder_referral", "no_reply"]
    assert len({d["reason"] for d in [interest, budget, referral, no_reply]}) == 4
