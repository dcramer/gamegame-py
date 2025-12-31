# Scythe QA Example

This document provides test questions and expected answers for QA testing the chat endpoint using Scythe.

## Prerequisites

- Game slug: `scythe-2016`
- Ensure the Scythe rulebook resource is processed (`status: completed`)

## Running Tests

```bash
# Quick test
mise cli ask scythe-2016 "How does the game end?"

# Verbose mode (see search results and tool calls)
mise cli ask scythe-2016 -v "How does the game end?"

# Interactive mode for multiple questions
mise cli ask scythe-2016
```

## Test Questions

### Q1: Simple - Game End Condition

**Question:** "How does the game end?"

**Expected Answer Should Include:**
- The game ends immediately when any player places their 6th star on the Triumph Track
- The game ends even if the player has other actions they could take

**Evaluation:**
- [ ] Mentions 6th star
- [ ] Mentions Triumph Track
- [ ] Indicates the game ends immediately

---

### Q2: Simple - River Movement

**Question:** "Can units cross rivers?"

**Expected Answer Should Include:**
- By default, units cannot cross rivers or move onto lakes
- Mechs can unlock the Riverwalk ability to cross rivers
- Riverwalk allows crossing onto specific terrain types (varies by faction)
- Some factions have alternative abilities (Submerge for lakes, etc.)

**Evaluation:**
- [ ] States default restriction (no river crossing)
- [ ] Mentions Riverwalk mech ability
- [ ] Notes terrain-specific crossing rules

---

### Q3: Medium - Combat Ties

**Question:** "What happens when combat is tied?"

**Expected Answer Should Include:**
- If power totals are tied, the attacker wins
- Both players reduce their power by the amount shown on their dials
- Both players discard any combat cards they used
- The loser retreats all units (character, mechs, workers) to their home base
- Resources remain on the contested territory
- The winner may place a star (maximum 2 combat stars total)
- If the attacker wins, they lose 1 popularity per enemy worker that retreats

**Evaluation:**
- [ ] Attacker wins ties
- [ ] Power reduction mentioned
- [ ] Retreat to home base mentioned
- [ ] Popularity loss for attacking winner (per worker) mentioned

---

### Q4: Medium - Encounters

**Question:** "How do encounters work?"

**Expected Answer Should Include:**
- Only the character can trigger encounters (not mechs or workers)
- Moving onto a territory with an encounter token ends the character's movement
- Resolve any combat first before the encounter
- Draw the top encounter card and choose one of three options
- Must be able to pay any costs required by the chosen option
- Gained resources, structures, or units go on the encounter territory
- The encounter token is discarded after resolution

**Evaluation:**
- [ ] Character-only restriction mentioned
- [ ] Movement ends on encounter
- [ ] Combat before encounter
- [ ] Choose 1 of 3 options
- [ ] Resources placed on that territory

---

### Q5: Complex - Mech Transport and Combat

**Question:** "Can mechs transport workers during movement, and what happens to them in combat?"

**Expected Answer Should Include:**
- Yes, mechs can pick up and drop off any number of workers during a Move action
- Workers can be picked up from any territory the mech moves through
- Workers can be dropped off on any territory the mech moves through
- Mechs cannot transport the character (only workers)
- If a mech with workers loses combat, all units retreat together to home base
- **Key nuance about popularity:**
  - The ATTACKER loses popularity only when they WIN and cause enemy workers to retreat
  - If the attacker LOSES combat, there is no popularity loss for their own transported workers retreating

**Evaluation:**
- [ ] Confirms mechs can transport workers
- [ ] Pick up/drop off during movement
- [ ] Cannot transport character
- [ ] Workers retreat with mech if combat lost
- [ ] Correct popularity rule: attacker loses popularity only when WINNING (not when losing)

---

## Scoring Guide

For each question, rate the response:

| Score | Criteria |
|-------|----------|
| **Pass** | All key points covered, no incorrect information |
| **Partial** | Most key points covered, minor omissions |
| **Fail** | Missing critical information or incorrect statements |

## Common Issues to Watch For

1. **Hallucination**: Inventing rules not in the rulebook
2. **Incomplete answers**: Missing key nuances (especially for complex questions)
3. **Wrong citations**: Citing non-existent page numbers or resources
4. **Missing follow-ups**: Not suggesting relevant follow-up questions
