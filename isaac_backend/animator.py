import omni.anim.graph.core as ag
from pxr import Usd


def _find_skel_animation(prim_path, stage):
    """Walk the character USD to find the first SkelAnimation prim (idle/stand)."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return None
    for child in Usd.PrimRange(prim):
        if child.GetTypeName() == "SkelAnimation":
            return str(child.GetPath())
    return None


def get_animator(character_path):
    """Get CharacterAnimator for a character. Must be called in Play mode."""
    return ag.get_character_animator(character_path)


def play_idle(character_path, stage):
    """Play idle/stand animation on character via direct-mode API."""
    animator = get_animator(character_path)
    if animator is None:
        print(f"[WARN] No animator for {character_path}")
        return None

    anim_path = _find_skel_animation(character_path, stage)
    if anim_path is None:
        print(f"[WARN] No idle animation found for {character_path}")
        return None

    anim = ag.load_animation(anim_path, looping=True, blend_in=0.3)
    anim_id = animator.play_animation(anim)
    print(f"[INFO] Playing idle on {character_path} (anim_id={anim_id})")
    return anim_id


def play_walk(character_path, anim_path, blend_in=0.3):
    """Play walk animation on character via direct-mode API."""
    animator = get_animator(character_path)
    if animator is None:
        print(f"[WARN] No animator for {character_path}")
        return None

    anim = ag.load_animation(anim_path, looping=True, blend_in=blend_in)
    anim_id = animator.play_animation(anim)
    print(f"[INFO] Playing walk on {character_path} (anim_id={anim_id})")
    return anim_id


def stop_animation(character_path, anim_id):
    """Stop an animation with blend-out."""
    animator = get_animator(character_path)
    if animator and anim_id is not None:
        animator.stop_animation(anim_id)
        print(f"[INFO] Stopped animation {anim_id} on {character_path}")


def set_variable(character_path, var_name, value):
    """Set an animation graph variable on a character."""
    character = ag.get_character(character_path)
    if character is None:
        print(f"[WARN] No character instance for {character_path}")
        return
    character.set_variable(var_name, value)
    print(f"[INFO] Set {var_name}={value} on {character_path}")
