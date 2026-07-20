# -*- coding: utf-8 -*-
import os, sys, re
from _bootstrap import tb

# Every callback_data example that should be GATED (biology/physics/chemistry)
GATED_EXAMPLES = [
    "menu_biology", "menu_tickets", "menu_questions",
    "quiz_start", "quiz_show_answer", "quiz_know", "quiz_dont_know", "quiz_stop",
    "random_ticket", "question_random", "question_by_number", "question_search",
    "ticket:12", "ticket_q:12:1", "qpage:2", "q:42",
    "menu_physics", "physics_tickets", "physics_theory_tickets", "physics_test_tickets",
    "phys_test_ticket:3", "physics_test", "physics_page:1", "physics_q:10",
    "physics_tasks", "phystask_topic:1", "phystask_formulas:1", "phystask_list:1", "phystask_show:1:2",
    "menu_chemistry", "chemistry_theory", "chem_theory:1", "chemistry_theory_list",
    "chemistry_tasks", "chemtask_topic:1", "chemtask_formulas:1", "chemtask_list:1", "chemtask_show:1:2",
    "chemistry_labs", "lab:1", "lab_exp:1:2", "lab_calc:1:2",
]

# Every callback_data example that should be EXEMPT (always accessible)
EXEMPT_EXAMPLES = [
    "back_to_main",
    "referral_info", "referral_leaderboard", "referral_battle",
    "support_menu", "toggle_donor_visibility", "donors_leaderboard",
    "donate_stars_menu", "donate_stars_amount:100", "donate_stars_confirm:100",
    "donate_stars_custom", "donate_rubles_menu", "donate_rubles_amount:500",
    "donate_rubles_confirm:500", "donate_rubles_custom",
    "admin_panel", "admin_battle_menu", "admin_battle_start_confirm", "admin_battle_start_go",
    "admin_battle_end_confirm", "admin_battle_end_go", "admin_stats", "admin_userlist:0",
    "admin_grant_prompt", "admin_revoke_prompt", "admin_dm_prompt", "admin_donation_prompt",
    "admin_announce_support_confirm", "admin_announce_support_go",
    "admin_channel_post_prompt", "admin_channel_post_go", "admin_channel_post_cancel",
    "anatomy_menu", "anatomy_osteology", "anatomy_topic:skull", "anatomy_bones:skull",
    "anatomy_bone_hub:skull:frontal", "anatomy_bone_material:skull:frontal:0",
    "anatomy_bone_img:skull:frontal:0", "anatomy_bone_flash_start:skull:frontal",
    "anatomy_bone_match_start:skull:frontal", "anatomy_bone_mnemonics:skull:frontal:0",
    "anatomy_material_list:skull", "anatomy_material:skull:0", "anatomy_flash_start:skull",
    "anatomy_flash_show_answer", "anatomy_flash_know", "anatomy_flash_dont_know", "anatomy_flash_stop",
    "anatomy_match_start:skull", "anatomy_match_answer:0", "anatomy_match_stop",
    "anatomy_mnemonics:skull:0", "anatomy_picture:skull",
]

fail = False
for cb in GATED_EXAMPLES:
    if not tb.is_gated_callback(cb):
        print(f"FAIL: expected GATED but was EXEMPT -> {cb}")
        fail = True
for cb in EXEMPT_EXAMPLES:
    if tb.is_gated_callback(cb):
        print(f"FAIL: expected EXEMPT but was GATED -> {cb}")
        fail = True

if fail:
    sys.exit(1)
print(f"Checked {len(GATED_EXAMPLES)} gated + {len(EXEMPT_EXAMPLES)} exempt callbacks — all correct")

# Cross-check against every actually-registered callback filter in the dispatcher,
# to catch anything the manual lists above missed.
import inspect
handlers = tb.dp.observers["callback_query"].handlers
missing_from_lists = []
for h in handlers:
    for f in h.filters:
        cb_filter = f.callback
        # aiogram MagicFilter reprs like "F.data == 'x'" or "F.data.startswith('x')"
        rep = repr(cb_filter)
        m = re.search(r"data == '([^']+)'", rep)
        if m:
            example = m.group(1)
        else:
            m = re.search(r"data\.startswith\(\('([^']+)',?\)?\)", rep)
            if not m:
                m = re.search(r"data\.startswith\('([^']+)'\)", rep)
            if not m:
                continue
            prefix = m.group(1)
            example = prefix + "1" if not prefix.endswith(":") else prefix + "1:1"
        if example not in GATED_EXAMPLES and example not in EXEMPT_EXAMPLES and not example.startswith(("anatomy_", "admin_", "donate_")):
            missing_from_lists.append((example, rep))

print("Handlers not covered by either list (informational):", missing_from_lists)
