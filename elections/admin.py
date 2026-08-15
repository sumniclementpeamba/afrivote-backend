from django.contrib import admin
from .models import Election, Position, Candidate, Voter, Vote, VoterRecord

@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'status', 'start_date', 'end_date')
    list_filter = ('status', 'election_type', 'organization')
    search_fields = ('title', 'organization__name')

@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('title', 'election', 'max_selections', 'is_required')

@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('name', 'position', 'organization', 'is_approved', 'is_active')

@admin.register(Voter)
class VoterAdmin(admin.ModelAdmin):
    list_display = ('voter_id', 'email', 'first_name', 'last_name', 'organization', 'is_verified')
    list_filter = ('organization', 'is_verified', 'is_active')
    search_fields = ('voter_id', 'email', 'first_name', 'last_name')

@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ('election', 'position', 'candidate', 'voted_at')
    list_filter = ('election', 'position')

@admin.register(VoterRecord)
class VoterRecordAdmin(admin.ModelAdmin):
    list_display = ('voter', 'election', 'voted_at')
    list_filter = ('election',)