
_yap-commands () {
    local -a commands

    commands=(
	'add:add a new file to the repository'
	'branch:list, create, or delete branches'
	'cherry-pick:apply the changes in a given commit to the current branch'
	'clone:make a local copy of an existing repository'
	'commit:record changes to files as a new commit'
	'diff:show staged, unstaged, or all uncommitted changes'
        'fetch:retrieve commits from a remote repository'
	'history:alter history by dropping or amending commits'
	'init:turn a directory into a repository'
	'log:show the changelog for particular versions or files'
        'merge:merge a branch into the current branch'
        'plugins:show information about loaded plugins'
	'point:move the current branch to a different revision'
        'push:send local commits to a remote repository'
	'repo:list, add, or delete configured remote repositories'
	'revert:remove uncommitted changes from a file (*)'
	'resolved:mark files with conflicts as resolved'
	'rm:delete a file from the repository'
	'show:show the changes introduced by a given commit'
	'stage:stage changes in a file for commit'
	'status:show files with staged and unstaged changes'
	'switch:change the current working branch'
	'track:query and configure remote branch tracking'
	'uncommit:reverse the actions of the last commit'
	'unstage:unstage changes in a file'
	'update:update the current branch relative to its tracking branch'
	'version:report the current version of yap'
    )

    _describe -t commands 'zsh command' commands && ret=0
}

_yap-unstage () {
    _arguments \
	'*:file:_files' && ret=0
}

_yap-stage () {
    _arguments \
	'*:file:_files' && ret=0
}

_yap-add () {
    _arguments \
	'*:file:_files' && ret=0
}

_yap-rm () {
    _arguments \
	'*:file:_files' && ret=0
}

_yap-log () {
    _arguments \
	'*:file:_files' && ret=0
}

_yap-resolved () {
    _arguments \
	'*:file:_files' && ret=0
}

_yap-switch () {
    _arguments \
	'*:branch:__git_heads' && ret=0
}

_yap-branch () {
    _arguments \
	'-d[delete a branch]:local branch' \
	'*:branch:__git_heads' && ret=0
}

_yap-commit () {
    _arguments \
	'(-d)-a[commit all changes]' \
	'(-a)-d[commit only staged changes]' \
	'-m[specify commit message]:commit message' && ret=0
}

_yap-diff () {
    _arguments \
	'(-u)-d[show only staged changes]' \
	'(-d)-u[show only unstaged changes]' && ret=0
}

__yap_repos () {
    repos=( `yap repo | gawk '{print $1}'` )
    compadd - "${repos[@]}"
}

_yap-repo () {
    _arguments \
	'-d[delete a repository]' \
        ':repo:__yap_repos' \
        '*:url' && ret=0
}

_yap-fetch () {
    _arguments \
        ':repo:__yap_repos' && ret=0
}

_yap-log () {
    _arguments \
        '-r:revision:__git_heads' \
        '*:files:_files' && ret=0
}

_yap-merge () {
    _arguments \
        ':branch:__git_heads' && ret=0
}

_yap-push () {
    _arguments \
        ':repo:__yap_repos' \
        ':branch:__git_heads' && ret=0
}

_yap-track () {
    _arguments \
        ':repo:__yap_repos' \
        ':branch:__git_heads' && ret=0
}

_yap () {
    if (( CURRENT == 2 )); then
	_yap-commands
    else
	shift words
	(( CURRENT-- ))
	curcontext="${curcontext%:*:*}:yap-$words[1]:"
	_call_function ret _yap-$words[1]
    fi
}

compdef _yap yap
