# Tournament Stages Inline Admin Analysis

## Current Tournament Admin Interface

**URL:** `/admin/tournaments/tournament/13/change/`

### Stages Section Structure

The tournament admin has a **STAGES** inline admin section with the following fields:

#### Table Headers:
1. **STAGE NUMBER** - Integer field
2. **NAME** - Text field (e.g., "Main Stage")
3. **FORMAT** - Dropdown with options:
   - Swiss System
   - Smart Swiss System
   - WTF (πετΑ Index)
   - Poules/Groups
   - Knockout
   - Round Robin
4. **NUM ROUNDS IN STAGE** - Integer field
5. **NUM QUALIFIERS** - Integer field (with help icon)
6. **NUM MATCHES PER TEAM** - Integer field (with help icon)
7. **DELETE?** - Checkbox

#### Features:
- ✅ Inline table format
- ✅ Multiple stages can be added
- ✅ "Add another Stage" button
- ✅ Each stage has its own row with all fields
- ✅ Format dropdown for each stage
- ✅ Delete checkbox for each stage

### Current Model: Stage

**App:** tournaments
**Model:** Stage
**Relationship:** ForeignKey to Tournament

**Fields visible in admin:**
- stage_number
- name
- format (choices: swiss, smart_swiss, wtf, poules, knockout, round_robin)
- num_rounds_in_stage
- num_qualifiers
- num_matches_per_team

---

## Required for Scenario Admin

We need to create a similar inline admin for **TournamentScenario** that allows admins to configure stages that will be used as a template when tournaments are created from that scenario.

### New Model Needed: ScenarioStage

**App:** simple_creator
**Model:** ScenarioStage
**Relationship:** ForeignKey to TournamentScenario

**Fields:**
- scenario (ForeignKey to TournamentScenario)
- stage_number (PositiveIntegerField)
- name (CharField)
- format (CharField with choices matching Stage.FORMAT_CHOICES)
- num_rounds_in_stage (PositiveIntegerField, null=True, blank=True)
- num_qualifiers (PositiveIntegerField, null=True, blank=True)
- num_matches_per_team (PositiveIntegerField, null=True, blank=True)

### Inline Admin Needed: ScenarioStageInline

**Class:** ScenarioStageInline(admin.TabularInline)
**Model:** ScenarioStage
**Extra:** 1 (show one empty form by default)

**Fields to display:**
- stage_number
- name
- format
- num_rounds_in_stage
- num_qualifiers
- num_matches_per_team

---

## Implementation Plan

1. **Create ScenarioStage model** in simple_creator/models.py
2. **Create migration** for ScenarioStage
3. **Create ScenarioStageInline** in simple_creator/admin.py
4. **Add inline to TournamentScenarioAdmin**
5. **Remove JSON stages field** from scenario admin
6. **Update tournament creation logic** to copy ScenarioStages to Stages

---

## Benefits

1. **User-Friendly:** Visual table interface instead of JSON
2. **Validation:** Django form validation instead of manual JSON parsing
3. **Consistency:** Same interface as tournament stages
4. **Error Prevention:** Dropdown choices prevent typos
5. **Easy to Use:** Add/remove stages with buttons
