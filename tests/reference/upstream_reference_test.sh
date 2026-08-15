#!/bin/sh

set -eu

repo_root=${1:?usage: upstream_reference_test.sh REPOSITORY_ROOT}
reference_dir="$repo_root/reference/upstream/twm-1.0.13.1"
archive="$reference_dir/twm-1.0.13.1.tar.xz"

fail()
{
    echo "upstream reference validation failed: $*" >&2
    exit 1
}

file_hash()
{
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{ print $1 }'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{ print $1 }'
    else
        fail "neither sha256sum nor shasum is available"
    fi
}

check_hash()
{
    path=$1
    expected=$2
    actual=$(file_hash "$reference_dir/$path")
    test "$actual" = "$expected" ||
        fail "$path has SHA-256 $actual, expected $expected"
}

compare_member()
{
    member=$1
    copy=$2
    tar -xOf "$archive" "twm-1.0.13.1/$member" |
        cmp - "$reference_dir/$copy" >/dev/null ||
        fail "$copy differs from archive member $member"
}

check_hash twm-1.0.13.1.tar.xz \
    a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5
check_hash SHA256SUMS \
    b8b020ea1b51a30cc9575182c157a926ba5bdd8be3bfdb17eca8e655ef1fce4a
check_hash twm-1.0.13.1.tar.xz.sig \
    39dd274c539b74675fbf0f367711dedc590274313c31678cbbf52f35572af666
check_hash release-signer.asc \
    eec7eccb51a27ae633784d1b1ef42eb775130c782ea51a6c47fa7a901484d6db
check_hash man/twm.man \
    a1743a47770bd63a2ff5e63b8c6e86d72ee02ddd126813951833fb33b8a56674
check_hash defaults/system.twmrc \
    861237bbfeacad152338019dc0cc84ec5bc50f147ca8b094335aaf99b750031d
check_hash defaults/gen_deftwmrc.sh \
    e91e71789c3d47358497e7c5d927b246b18033fa35a254a011b99ef763ca4adf
check_hash defaults/deftwmrc.c \
    e26b85fce8b291735c698b3d41f9c7d482e8eb93e22e17a91b9292835bd7a570
check_hash sample-twmrc/jim.twmrc \
    704e2699d9677b3b976df13277e8147efd04e24027714a319012670013848ee3
check_hash sample-twmrc/keith.twmrc \
    fe33be5f80e238f1a5aefd3ffad0637d356c3ba34714870d8df8414723365e08
check_hash sample-twmrc/lemke.twmrc \
    6f8406d44c9176935bb38d0668a866c216a21b9857593eea234bc93b3f186130

bad_member=$(tar -tf "$archive" | awk '$0 !~ /^twm-1\.0\.13\.1\// { print; exit }')
test -z "$bad_member" || fail "archive has an unexpected root: $bad_member"

tar -xOf "$archive" twm-1.0.13.1/configure.ac |
    grep -Fq 'AC_INIT([twm], [1.0.13.1],' ||
    fail "archive configure.ac does not declare twm 1.0.13.1"

compare_member man/twm.man man/twm.man
compare_member src/system.twmrc defaults/system.twmrc
compare_member src/gen_deftwmrc.sh defaults/gen_deftwmrc.sh
compare_member src/deftwmrc.c defaults/deftwmrc.c
compare_member sample-twmrc/jim.twmrc sample-twmrc/jim.twmrc
compare_member sample-twmrc/keith.twmrc sample-twmrc/keith.twmrc
compare_member sample-twmrc/lemke.twmrc sample-twmrc/lemke.twmrc

sample_members=$(tar -tf "$archive" |
    awk 'index($0, "twm-1.0.13.1/sample-twmrc/") == 1 {
        sub(/^twm-1\.0\.13\.1\/sample-twmrc\//, "")
        if (index($0, "/") == 0 && $0 ~ /[.]twmrc$/) print
    }' | LC_ALL=C sort)
expected_samples=$(printf '%s\n' jim.twmrc keith.twmrc lemke.twmrc)
test "$sample_members" = "$expected_samples" ||
    fail "archive sample configuration set has drifted"

if command -v gpg >/dev/null 2>&1; then
    gpg_home=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-reference-gpg.XXXXXX") ||
        fail "could not create temporary GnuPG home"
    chmod 700 "$gpg_home"
    trap 'if test -n "${gpg_home:-}"; then rm -rf "$gpg_home"; fi' 0 1 2 15

    gpg --no-autostart --homedir "$gpg_home" --batch --quiet \
        --import "$reference_dir/release-signer.asc" 2>/dev/null ||
        fail "could not import the pinned release signer"
    signature_status=$(gpg --no-autostart --homedir "$gpg_home" --batch \
        --status-fd=1 --verify "$reference_dir/twm-1.0.13.1.tar.xz.sig" \
        "$archive" 2>/dev/null) || fail "detached signature is invalid"
    printf '%s\n' "$signature_status" |
        grep -Fq '[GNUPG:] VALIDSIG 19882D92DDA4C400C22C0D56CC2AF4472167BE03 ' ||
        fail "detached signature does not use the pinned signer fingerprint"

    rm -rf "$gpg_home"
    gpg_home=
fi
